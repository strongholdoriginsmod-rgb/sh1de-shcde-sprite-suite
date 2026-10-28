using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using CrusaderDE;
using HarmonyLib;
using R3;
using SHCDESE.API;
using SHCDESE.API.Components.SaveData;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Projectiles;
using SHCDESE.EventAPI.MapLoader;
using SHCDESE.EventAPI.Tribes;
using SHCDESE.EventAPI.Units;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;
using SHCDESE.Lua;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Gives hunters and woodcutters a bounded, per-unit militia controller
    /// without adding either worker to the troop-production UI.
    /// </summary>
    /// <remarks>
    /// The first implementation assigned workers to a temporary tribe and
    /// treated an accepted AttackUnit command as proof that they could execute
    /// soldier AI. That assumption was false: worker update functions do not
    /// traverse the soldier/Lord combat state machine. This implementation
    /// therefore owns the small missing adapter explicitly. It uses the native
    /// per-unit move order, real native projectiles and the native melee damage
    /// entry point, while leaving production links and tribe ownership intact.
    /// The one tribe change this feature must tolerate is not its own: the
    /// native selection commit groups every selected unit into a fresh
    /// singleton tribe and native deselection dissolves it again (see
    /// <see cref="TribeProvenanceMatches"/>); treating that as a provenance
    /// violation made every first confirmed selection fail closed.
    /// </remarks>
    internal sealed class WorkerMilitiaFeature : IExtensionFeature
    {
        private const int ValidTargetCount = (int)eChimps.CHIMP_NUM_TYPES;
        private const int ExpectedEnumCount = ValidTargetCount + 1;
        private const int MaxInputPackets = 32;
        private const int MaxSavedCommands = 128;
        private const int MaxMapTile = 799;
        private const int RightClickGestureTimeoutMilliseconds = 3000;
        private const float NativeSelectionBoxThresholdPixels = 16f;
        // Pinned CrusaderDE.dll selection layout. RVA 0x18ED50 only builds the
        // hovered/candidate set: it writes GameUnit +0x30 and manager +0x20.
        // It does not commit a command selection. A normal non-Shift direct
        // click replaces the old selection at RVA 0x8BF40, builds its marker
        // through RVA 0x18C490/0x1815D0, and commits the resulting singleton on
        // mouse-up through RVA 0x1901F0/chore 0x10. RVA 0x1905C0/chore 0x48 is
        // the separate Shift-toggle path and must not be called as a shortcut.
        // Its handler's fourth argument is a destination tribe ID, not a unit
        // owner, and direct calls bypass the normal queue/UI lifecycle. Native
        // unit deselection is likewise a two-step operation: RVA 0x185960
        // clears +0x30/manager +0x20, then RVA 0x199300 clears +0xAE and manager
        // +0x24+(player*4) for that exact unit. The local single-player selected
        // count is manager +0x28 and its ordered IDs are exported through
        // EngineInterface.selectedChimps.
        private const int NativeGameUnitSize = 0x490;
        private const int NativeGameBuildingSize = 0x32C;
        private const int NativeUnitAliveStateOffset = 0x88;
        private const int NativeUnitTypeOffset = 0x8A;
        private const int NativeUnitOwnerOffset = 0x92;
        private const int NativeUnitGlobalIdOffset = 0x94;
        private const int NativeUnitWorldPositionXOffset = 0xB2;
        private const int NativeUnitWorldPositionYOffset = 0xB4;
        private const int NativeSelectedOffset = 0x30;
        private const int NativeSelectionAuxiliaryOffset = 0xAC;
        private const int NativeSelectionOwnerOffset = 0xAE;
        private const int NativeSelectionBlockerOffset = 0x29C;
        private const int NativeCommandModeOffset = 0x2A0;
        private const int NativeAiStateOffset = 0x2BC;
        private const int NativeMilitiaMoveState =
            WorkerMilitiaHunterMoveState.NativeMoveState;
        private const int NativeUnitTribeOffset = 0x2D4;
        private const int NativeUnitWorkLinkOffset = 0x334;
        private const int NativeSelectionRelevantOffset = 0x354;
        // Native worker census at CrusaderDE.dll RVA 0x0C84E0 reads the
        // upper ushort of N000000C5 as a zero-based workplace slot and the
        // lower ushort of N000001D8 as its building ID. The fields remain
        // strictly read-only here; their split offsets are pinned separately.
        private const int NativeUnitOccupancySlotContainerOffset = 0x390;
        private const int NativeUnitOccupancySlotOffset = 0x392;
        private const int NativeUnitOccupancyBuildingOffset = 0x394;
        // Native command marker ("order accepted" cone/flash the game draws on
        // a commanded unit). Pinned on the same CrusaderDE.dll: the tribe move
        // order at RVA 0x11A3C0 sets the low ushort of GameUnit +0x78 to 16 in
        // each of its accepted branches (0x11AEC9, 0x11AF87, 0x11AFA3); the
        // per-selection-tribe renderer at RVA 0x121140 reads that counter and
        // draws sprite frame (106 - counter) with a palette that switches at
        // counter < 8; the per-unit tick at RVA 0x183B5D decrements it back to
        // zero on its own. Writing 16 therefore reproduces exactly what the
        // native order does and needs no rollback - it decays by itself.
        private const int NativeCommandMarkerContainerOffset = 0x78;
        private const int NativeCommandMarkerValue = 16;
        // A commanded worker that has not advanced a single tile for this long
        // lost its native order; only then is the same destination re-sent.
        private const int MoveStallMilliseconds = 2000;
        private const int ManualMoveAbortMilliseconds = 8000;
        private const int ManualMoveAbortRetryFloor = 3;
        private const int MaxAnimationProbes = 40;
        private const int MaxAiStateTransitions = 80;
        private const int ProjectileProbeFloorPerCohort = 20;
        private const int MaxOwnedProjectiles = 128;
        private const int OwnedProjectileLifetimeMilliseconds = 30000;
        // SHCDESE states the ratio explicitly: one local tile is eight
        // world tiles. Unit positions in this feature are local tiles,
        // projectile events are world tiles.
        private const int WorldTilesPerLocalTile = 8;
        private const int MaxCursorSamplesLogged = 12;
        // War 5. Der Lauf vom 30.08. 14:22 schrieb damit nach genau fuenf
        // Beobachtungen den Jaeger auf Sprite-Basis 13 - ein Wert, der in
        // derselben Partie nie ein stabiler Mehrheitswert wurde (Endstand 0
        // aus 568 Beobachtungen). Fuenf Sichtungen sind keine Mehrheit,
        // sondern der Anfang einer Messreihe.
        //
        // Der Boden bleibt stehen, auch wenn beide Schreibzugriffe derzeit
        // abgeschaltet sind: er begrenzt, was ein spaeterer Versuch fuer
        // "gelernt" halten darf.
        private const int WalkStateEvidenceFloor = 120;
        // The cursor graphic is not driven by cursor_kind alone. At RVA
        // 0x8E3EA the "order not possible" branch writes five globals in
        // one go: 0x60AB4A8=0x41, 0x60AB4AC=0xAC, 0x60AB4B0=0x10,
        // 0x60AB4BC=0x11 and cursor_kind 0x60AB4C0=-10. Writing only the
        // kind changed nothing on screen (measured 2026-08-19 20:25), so
        // the whole block from 0x60AB4A8 to 0x60AB4C0 is captured and
        // replayed as one unit.
        private static int NativeCursorBlockRva { get { return NativeLayout.CursorBlockRva; } }
        private const int NativeCursorBlockDwords = 7;
        private const int NativeCursorKindBlockIndex = 6;
        private const int NativeBuildingAliveStateOffset = 0xD0;
        private const int NativeBuildingTypeOffset = 0xD2;
        private const int NativeBuildingOwnerOffset = 0xD6;
        private const int NativeBuildingGlobalIdOffset = 0xD8;
        private const int NativeBuildingWorldPositionXOffset = 0xE8;
        private const int NativeBuildingWorldPositionYOffset = 0xEA;
        private const int NativeBuildingRequiredWorkersOffset = 0x198;
        private const int NativeBuildingCurrentWorkersOffset = 0x19A;
        private const int NativeBuildingMissingWorkersOffset = 0x19C;
        private const int NativeBuildingWorkerIdOffset = 0x19E;
        private const int NativeBuildingWorkerGlobalIdOffset = 0x1A8;
        private const int NativeWorkerSlotCount = 4;
        // CrusaderDE.dll RVA 0x19EB3D serializes the worker-information name
        // bytes from GameUnit +0x3E8. SHCDESE exposes those two bytes as the
        // pinned ushort below (low byte = name, high byte = surname).
        private const int NativeWorkerNameOffset = 0x3E8;
        private static int NativeUnitManagerRva { get { return NativeLayout.UnitManagerRva; } }
        private const int NativeHoveredCountOffset = 0x20;
        private const int NativeSelectedCountBaseOffset = 0x24;
        private const int MaxNativeSelectedUnits = 10000;
        private const int NativeSelectedPairBufferLength = 20000;
        private static int NativeUnitSelectionMarkerClearRva { get { return NativeLayout.UnitSelectionMarkerClearRva; } }
        private static int NativePlayerSelectionClearRva { get { return NativeLayout.PlayerSelectionClearRva; } }
        private const int NativeSelectionVerificationMilliseconds = 3000;
        private const int WorkResumptionProofTimeoutMilliseconds = 15000;
        // Every engine address lives in WorkerMilitiaNativeLayout, one record
        // per CrusaderDE.dll build. Prepare declines on an unknown build, so
        // every path past Prepare may read this without a null check.
        private static WorkerMilitiaNativeLayout NativeLayout
        {
            get { return WorkerMilitiaNativeLayout.Current; }
        }
        private const string NativeDeselectionReleaseReason = "native deselection";
        // Read-only evidence globals of the pinned CrusaderDE.dll input handler
        // (RVA 0x8B600): selection state machine, command cursor mode, the
        // tribe the last commit stored for the selection, cursor target kind,
        // HUD sub mode, active mapper item, candidate count passed by Unity,
        // and the mouse bits the engine saw last. Only dumped around a
        // captured right-click so the native reaction can be read from a log.
        private static int NativeSelectionStateRva { get { return NativeLayout.SelectionStateRva; } }
        private static int NativeCursorKindRva { get { return NativeLayout.CursorKindRva; } }
        private static int NativeMapperItemRva { get { return NativeLayout.MapperItemRva; } }
        private static int NativeSelectionTribeRva { get { return NativeLayout.SelectionTribeRva; } }
        private static int NativeSelectionPendingRva { get { return NativeLayout.SelectionPendingRva; } }
        private static int NativeSelectionFlagRva { get { return NativeLayout.SelectionFlagRva; } }
        private static int NativeHudSubModeRva { get { return NativeLayout.HudSubModeRva; } }
        private static int NativeHudPrevSubModeRva { get { return NativeLayout.HudPrevSubModeRva; } }
        private static int NativeAppModeRva { get { return NativeLayout.AppModeRva; } }
        private static int NativeAppSubModeRva { get { return NativeLayout.AppSubModeRva; } }
        private static int NativeCandidateCountRva { get { return NativeLayout.CandidateCountRva; } }
        private static int NativeLastMouseStateRva { get { return NativeLayout.LastMouseStateRva; } }
        private static int NativeLastRightDownRva { get { return NativeLayout.LastRightDownRva; } }
        private static int NativeLastRightUpRva { get { return NativeLayout.LastRightUpRva; } }
        private static int NativeSelectionOnRva { get { return NativeLayout.SelectionOnRva; } }
        private static int NativeSelectionEstablishedRva { get { return NativeLayout.SelectionEstablishedRva; } }
        // REFUTED 2026-08-27, kept as a warning. Until then this file claimed
        // that the gate at RVA 0x8E398
        //     movsxd rdx,[rax+rsi+72Ch]
        //     test   dword ptr [rdi+rdx*4+898400h],10000100h
        //     je     0x8E3EA            ; cursor kind -10, "not possible"
        // reads a per-unit-type capability index. It does not. With the array
        // base at manager+0x65C - the same value Serpens66's independent tool
        // reports - every offset in that handler resolves to a named GameUnit
        // field, and all of them agree with the offsets already pinned above:
        //   +0x6E4 -> +0x88 r_AliveState        +0x6E6 -> +0x8A r_UnitChimp
        //   +0x6EE -> +0x92 r_ControllableFor.. +0x6F0 -> +0x94 r_GlobalId
        //   +0x68C -> +0x30 r_UnitSelected      +0x71C -> +0xC0 tile x
        //   +0x72C -> +0xD0 r_CurrentPositionTileId
        // so 0x8E398 is a TILE-flag test on the tile the unit stands on, and
        // the "capability table" was the map's tile-flag array. Writing to it
        // would have altered terrain flags. The code that did so is deleted;
        // do not reintroduce it. The real gate is the selection-class census
        // handled by WorkerMilitiaCommandClass.
        //
        // Selected-class counters of that census, manager+0x564, 35 entries.
        // Only read here, for evidence: index 0 is the archer class, which is
        // what a militia hunter is taught to count as.
        private const int NativeSelectionClassCounterBase = 0x564;
        private const int NativeSelectionClassCounterCount = 35;
        // Frueher ein harter Gesamtdeckel von 6. Die Methode laeuft auf dem
        // Engine-Faden bei JEDEM nativen Lauf, solange eine Miliz bestaetigt
        // ausgewaehlt ist - alle sechs Zeilen waren damit binnen etwa 100 ms
        // nach der ersten Anwahl verbraucht, alle aus derselben Cursorlage.
        // Die entscheidende Lage (Maus ueber freiem Boden, wo der Kegel
        // erscheinen muesste) kam nie ins Protokoll. Jetzt: eine Zeile je
        // unterschiedlicher Lage, mit einem Gesamtdeckel gegen Flut.
        private const int MaxCommandClassEvidenceLogs = 24;
        private const int MaxAnimationTraceLogs = 90;
        // Ein Spielstand kann bis zu MaxSavedCommands Eintraege tragen;
        // gedeckelt, damit ein alter Stand das Log nicht flutet.
        private const int MaxSaveRestoreLogs = 16;
        // One 240-sample window is roughly one minute at the generated 250 ms
        // scan cadence. Ten capped records cover the requested ten-minute
        // stress canary without a per-tick log stream.
        private const int PerformanceWindowSamples = 240;
        private const int MaxPerformanceEvidenceLogs = 10;
        private const int ScanCensusHeartbeatMilliseconds = 5000;
        // The Extender itself names the bound in its own error text
        // ("unit index that was out of range: [117670335/10000]"), so anything
        // at or above this is garbage and must never reach its API.
        private const int NativeMaxUnitId = 10000;
        private const int MaxCursorReplayLogs = 6;
        private const int NativeUnitManagerModeOffset = 0x10;
        private const int NativeUnitManagerPrevModeOffset = 0x14;
        private const int SelectionQuarantineGraceMilliseconds = 500;
        private const int SelectionQuarantineCleanRunFloor = 3;
        private const int SaveMagic = 0x53454D31;
        private const int LegacySaveVersion = 3;
        private const int SaveVersion = 4;
        private const int UnresolvedSavedTargetGlobalId = -1;
        private const string SaveDataIdentifier =
            "StrongholdEuropeDE.WorkerMilitia.v3";

        private static readonly object InputOwnerGate = new object();
        private static WorkerMilitiaFeature _inputOwner;

        private static readonly ExtensionLeaseClaim WoodcutterDamageClaim =
            ExtensionLeaseClaim.NativeTableRow(
                "GameUnitManagerAPI.MeleeDamageLookupTable",
                (int)eChimps.CHIMP_TYPE_WOODCUTTER);

        private static readonly ExtensionLeaseClaim HunterHutAvailabilityClaim =
            ExtensionLeaseClaim.Mapper((int)eMappers.MAPPER_HUNTER);

        private static readonly ExtensionLeaseClaim[] ManagedClaims =
        {
            ExtensionLeaseClaim.Unit((int)eChimps.CHIMP_TYPE_HUNTER),
            ExtensionLeaseClaim.Unit((int)eChimps.CHIMP_TYPE_WOODCUTTER),
            WoodcutterDamageClaim,
            ExtensionLeaseClaim.Hook("EditorDirector.getMouseStateForEngine"),
            ExtensionLeaseClaim.Hook("EngineInterface.run"),
            ExtensionLeaseClaim.Hook("EditorDirector.updateDLLSelectedTroops"),
            ExtensionLeaseClaim.Hook(
                "CrusaderDE.MainViewModel.TroopsSelectedGameAction"),
            ExtensionLeaseClaim.Hook(
                "SHCDESE.EventAPI.UnitR3EventHooks.OnUnitMoveHere"),
            ExtensionLeaseClaim.Hook(
                "SHCDESE.EventAPI.UnitR3EventHooks.OnUnitDelete"),
            ExtensionLeaseClaim.Hook(
                "SHCDESE.EventAPI.UnitR3EventHooks.OnUnitTakeProjectileDamageEx"),
            ExtensionLeaseClaim.Hook(
                "SHCDESE.EventAPI.UnitR3EventHooks.OnUnitTakeMeleeDamage"),
            ExtensionLeaseClaim.Hook(
                "SHCDESE.EventAPI.TribeR3EventHooks.OnTribeIssueOrderMoveHere"),
            ExtensionLeaseClaim.Hook(
                "SHCDESE.EventAPI.TribeR3EventHooks.OnTribeIssueOrderWithTarget"),
            HunterHutAvailabilityClaim,
            ExtensionLeaseClaim.Hook("CrusaderDE.MainViewModel.CanPlaceMapper"),
        };

        private sealed class UnitSnapshot
        {
            internal int Id;
            internal eChimps Type;
            internal int Owner;
            internal int X;
            internal int Y;
            internal int CombatX;
            internal int CombatY;
            internal int WorkLink;
            internal int TribeId;
            internal int GlobalId;
            internal long TileId;
        }

        /// <summary>
        /// Immutable main-thread sample consumed by the cone probe on the
        /// EngineInterface.run thread. It intentionally contains values, not
        /// an extender unit handle: resolving an id through the extender from
        /// that native postfix can terminate the game without a managed crash.
        /// </summary>
        private sealed class ConeUnitSample
        {
            internal readonly int Id;
            internal readonly int Type;
            internal readonly long TileId;
            internal readonly bool WasMoving;

            internal ConeUnitSample(
                int id,
                int type,
                long tileId,
                bool wasMoving)
            {
                Id = id;
                Type = type;
                TileId = tileId;
                WasMoving = wasMoving;
            }
        }

        private sealed class UnitSpatialIndex
        {
            private const int BucketSize = 16;
            private readonly Dictionary<long, List<UnitSnapshot>> _buckets =
                new Dictionary<long, List<UnitSnapshot>>();
            private readonly Dictionary<int, UnitSnapshot> _byId =
                new Dictionary<int, UnitSnapshot>();

            internal UnitSpatialIndex(List<UnitSnapshot> snapshots)
            {
                if (snapshots == null)
                {
                    return;
                }
                foreach (UnitSnapshot snapshot in snapshots)
                {
                    _byId[snapshot.Id] = snapshot;
                    int bucketX = snapshot.CombatX / BucketSize;
                    int bucketY = snapshot.CombatY / BucketSize;
                    long key = PackBucket(bucketX, bucketY);
                    List<UnitSnapshot> bucket;
                    if (!_buckets.TryGetValue(key, out bucket))
                    {
                        bucket = new List<UnitSnapshot>();
                        _buckets.Add(key, bucket);
                    }
                    bucket.Add(snapshot);
                }
            }

            internal int MinimumBucket(int tile, int radius)
            {
                return Math.Max(0, tile - radius) / BucketSize;
            }

            internal int MaximumBucket(int tile, int radius)
            {
                return Math.Min(MaxMapTile, tile + radius) / BucketSize;
            }

            internal List<UnitSnapshot> GetBucket(int bucketX, int bucketY)
            {
                List<UnitSnapshot> bucket;
                return _buckets.TryGetValue(
                        PackBucket(bucketX, bucketY),
                        out bucket)
                    ? bucket
                    : null;
            }

            internal UnitSnapshot FindById(int unitId)
            {
                UnitSnapshot snapshot;
                return _byId.TryGetValue(unitId, out snapshot)
                    ? snapshot
                    : null;
            }

            private static long PackBucket(int x, int y)
            {
                return ((long)x << 32) | unchecked((uint)y);
            }
        }

        private enum MissionPhase : byte
        {
            Outbound = 1,
            Fighting = 2,
            Holding = 3,
            DirectWorkPending = 4,
        }

        private enum NativeSelectionLifecycle : byte
        {
            Idle = 0,
            PacketInjected = 1,
            AwaitingCommit = 2,
            Confirmed = 3,
            CancelAwaitingCommit = 4,
            Quarantined = 5,
        }

        private sealed class CommandState
        {
            internal long Generation;
            internal int WorkerUnitId;
            internal int WorkerGlobalId;
            internal int WorkerOwner;
            internal eChimps WorkerType;
            internal int TargetUnitId;
            internal int TargetGlobalId;
            internal int OriginX;
            internal int OriginY;
            internal int OriginalWorkLink;
            internal int OriginalTribeId;
            internal bool Manual;
            internal bool ExplicitTarget;
            internal MissionPhase Phase;
            internal bool HasManualDestination;
            internal bool ManualDestinationReached;
            internal int ManualDestinationX;
            internal int ManualDestinationY;
            internal int CombatAnchorX;
            internal int CombatAnchorY;
            internal bool DamageObserved;
            internal int NextAttackTick;
            internal int NextMoveTick;
            internal int HoldDeadlineTick;
            // Simulation-bound movement bookkeeping. Version 4 stores every
            // deadline relative to the save tick; otherwise loading would
            // immediately re-send the native order, restart the walk animation
            // and erase the eight-second unreachable-target proof.
            internal bool HasIssuedMove;
            internal int IssuedMoveX;
            internal int IssuedMoveY;
            internal int LastProgressX;
            internal int LastProgressY;
            internal int LastProgressTick;
            internal int StallWindowStartTick;
            internal int StallRetryCount;
            internal bool ResumeHoldAfterCombat;
            internal int PausedHoldRemainingMilliseconds;
            internal bool DirectWorkCompletionPending;
            internal MissionPhase DirectWorkSnapshotPhase;
            internal int DirectWorkSnapshotTargetGlobalId;
            internal bool DirectWorkSnapshotExplicitTarget;
            internal int DirectWorkSnapshotHoldRemainingMilliseconds;
            internal ushort OriginalCommandModeValue;
            internal bool OwnsCommandMode;
            internal OccupancyProvenance Occupancy;
            // Der Arbeitsplatz dieses Arbeiters ist waehrend des Einsatzes
            // verschwunden - abgebrannt, abgerissen oder neu besetzt. Der
            // Auftrag wird damit am sicheren nativen Rand beendet; nur die
            // identitaetsgebundene Auswahl und der eigene Befehlsmodus werden
            // freigegeben. Die alte Arbeitsbindung wird niemals restauriert.
            internal bool WorkplaceLost;

            /// <summary>
            /// Der Arbeiter hatte beim Anlegen dieses Einsatzes schon keinen
            /// lebenden Arbeitsplatz mehr.
            /// </summary>
            /// <remarks>
            /// Zu unterscheiden von WorkplaceLost: dort geht ein Arbeitsplatz
            /// WAEHREND des Einsatzes verloren, und der Einsatz endet, damit
            /// Vanilla den Arbeiter neu zuteilen kann. Hier gab es von
            /// vornherein keinen - der Arbeiter ist bereits auf dem Weg zum
            /// Bergfried, wo er sich am Feuer zum Bauern aufloest. Dieser Weg
            /// gehoert Vanilla; der Mod haengt sich nicht hinein, macht den
            /// Arbeiter aber unterwegs wehrhaft. Anwaehlbar wird er dadurch
            /// nicht: TryArmNativeSelection verlangt weiterhin einen lebenden
            /// Arbeitsplatz.
            /// </remarks>
            internal bool Homeless;

            /// <summary>
            /// Welcher Weg das Ziel dieses Einsatzes gesetzt hat:
            /// "native OnUnitMoveHere" (die Engine hat den Befehl selbst
            /// erteilt) oder "right-click fallback" (die Engine hat ihn nicht
            /// erteilt, und der Mod hat MoveToTile benutzt).
            /// </summary>
            /// <remarks>
            /// Das ist die Messung fuer das Gleiten. Die Animation ist in
            /// dieser Engine keine eigene Schicht, sondern Eigenschaft der
            /// Verhaltensroutine: 487 Stellen schreiben den Sprite-Rahmen, 695
            /// den Animationstimer, alle im KI-Code. Wer nur die Position
            /// versetzt, ohne die Einheit in das Laufverhalten zu bringen,
            /// bekommt eine gleitende Einheit. Zwei unabhaengige Fehler
            /// erzwangen diesen Rueckfall: 0x18C1A0 lieferte urspruenglich -1,
            /// und nach dessen Reparatur blockierte OnTribeMoveOrder weiterhin
            /// Chore 0x11, bevor der Executor Zustand 0x65 setzen konnte. Die
            /// Spur bleibt erhalten, damit der Spiellauf den wirklich
            /// ausgefuehrten Weg belegt.
            /// </remarks>
            internal string OrderPath;
        }

        private sealed class OccupancyProvenance
        {
            internal int SlotIndex;
            internal int BuildingId;
            internal int BuildingGlobalId;
            internal eStructs BuildingType;
            internal int BuildingOwner;
            internal int RequiredWorkers;
        }

        private sealed class InputPacket
        {
            internal bool RightDown;
            internal int SelectedWorkerId;
            internal int SelectedWorkerGlobalId;
            internal int SelectedWorkerOwner;
            internal eChimps SelectedWorkerType;
            internal int HoveredUnitId;
            internal int HoveredUnitGlobalId;
            internal int HoveredUnitOwner;
            internal eChimps HoveredUnitType;
            internal bool HasGroundDestination;
            internal int GroundDestinationX;
            internal int GroundDestinationY;
            internal int NativeMoveSequenceAtCapture;
            internal bool NativeMoveObserved;
            internal bool NativeMoveAccepted;
            internal long NativeMoveReturnValue;
        }

        private sealed class PendingDirectWorkCompletion
        {
            internal CommandState Command;
            internal int WorkerUnitId;
            internal int WorkerGlobalId;
            internal int WorkerOwner;
            internal eChimps WorkerType;
            internal int OriginalWorkLink;
            internal int OriginalTribeId;
            internal string Reason;
            internal bool CombatCompleted;
            internal bool EmitRuntimeEvidence;
            internal bool Homeless;
            internal OccupancyProvenance Occupancy;
            internal MissionPhase SnapshotPhase;
            internal int SnapshotTargetGlobalId;
            internal bool SnapshotExplicitTarget;
            internal int SnapshotHoldRemainingMilliseconds;
        }

        private sealed class PendingWorkResumptionProof
        {
            internal int WorkerUnitId;
            internal int WorkerGlobalId;
            internal int WorkerOwner;
            internal eChimps WorkerType;
            internal int OriginalWorkLink;
            internal int OriginalTribeId;
            internal string Reason;
            internal string Mode;
            internal int DeadlineTick;
            internal OccupancyProvenance Occupancy;
        }

        private sealed class RightClickGesture
        {
            internal long Generation;
            internal InputPacket Packet;
            internal int DeadlineTick;
            internal int HoveredUnitIdAtDown;
            internal int NativeMouseStateAtDown;
            internal int NativeMouseStateAtUp;
            internal bool Released;
            // The engine ended the worker's native selection between the
            // captured mouse-down and the promotion (see
            // ReleaseNativeSelection). The captured packet still names the
            // exact worker slot, global id, owner and type, so the gesture is
            // completed against that identity instead of the vanished
            // selection and promoted into the mission path as usual.
            internal bool SelectionLostAfterCapture;
        }

        private sealed class PendingUiEvidence
        {
            internal MainViewModel ViewModel;
            internal long LeaseGeneration;
            internal int UnitId;
            internal int GlobalId;
            internal int Owner;
            internal eChimps Type;
            internal string Route;
            internal long DueTickGeneration;
        }

        private sealed class UiSelectionSnapshot
        {
            internal NativeSelectionLease Lease;
            internal long LeaseGeneration;
            internal int UnitId;
            internal int GlobalId;
            internal int Owner;
            internal eChimps Type;
        }

        private sealed class NativeSelectionLease
        {
            internal long Generation;
            internal int UnitId;
            internal int GlobalId;
            internal int Owner;
            internal eChimps Type;
            internal ushort OriginalCommandModeValue;
            internal ushort OriginalSelectionOwnerValue;
            internal int OriginalTribeId;
            internal int OriginalWorkLink;
            internal int OriginalX;
            internal int OriginalY;
            internal bool TemporarilySuppressed;
            // The native class-census patch is owned by this exact identity
            // generation. It may exist only while this lease exists; a reused
            // unit slot can therefore never inherit the widened type window.
            internal bool CommandClassApplied;
            internal int CommandClassThreadId;
            internal long CommandClassRunGeneration;
            internal bool ManagedGateTelemetryLogged;
            internal bool UiRouteTelemetryLogged;
            internal bool UiThreadMismatchTelemetryLogged;
            internal bool WorkerInformationCacheValid;
            internal string WorkerNameText;
            internal string WorkerTypeText;
            internal string WorkerCommentText;
            internal string WorkerWorkText;
            internal PendingUiEvidence UiEvidence;
            internal OccupancyProvenance Occupancy;
        }

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate void NativeUnitSelectionMarkerClear(
            IntPtr unitManager,
            int unitId);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate void NativePlayerSelectionClear(
            IntPtr unitManager,
            int selectionPlayer,
            int unitId,
            int nativeMode);

        private sealed class SavedCommand
        {
            internal long CommandGeneration;
            internal int WorkerUnitId;
            internal int WorkerGlobalId;
            internal eChimps WorkerType;
            internal int Owner;
            internal int TargetGlobalId;
            internal int OriginX;
            internal int OriginY;
            internal int OriginalWorkLink;
            internal int OriginalTribeId;
            internal bool Manual;
            internal bool ExplicitTarget;
            internal MissionPhase Phase;
            internal bool HasManualDestination;
            internal bool ManualDestinationReached;
            internal int ManualDestinationX;
            internal int ManualDestinationY;
            internal int CombatAnchorX;
            internal int CombatAnchorY;
            internal bool DamageObserved;
            internal int HoldRemainingMilliseconds;
            internal ushort OriginalCommandModeValue;
            internal bool WorkplaceLost;
            internal bool ResumeHoldAfterCombat;
            internal int PausedHoldRemainingMilliseconds;
            internal int NextAttackRemainingMilliseconds;
            internal int NextMoveRemainingMilliseconds;
            internal bool HasIssuedMove;
            internal int IssuedMoveX;
            internal int IssuedMoveY;
            internal int LastProgressX;
            internal int LastProgressY;
            internal int MoveStallRemainingMilliseconds;
            internal int StallWindowElapsedMilliseconds;
            internal int StallRetryCount;
            internal OccupancyProvenance Occupancy;
        }

        private sealed class OwnedProjectile
        {
            internal int ProjectileId;
            internal long MilitiaGeneration;
            internal int WorkerUnitId;
            internal int WorkerGlobalId;
            internal int WorkerOwner;
            internal eChimps WorkerType;
            internal int TargetUnitId;
            internal int TargetGlobalId;
            internal int ReferenceDamage;
            internal int DeadlineTick;
        }

        private sealed class SavedOwnedProjectile
        {
            internal int ProjectileId;
            internal long MilitiaGeneration;
            internal int WorkerUnitId;
            internal int WorkerGlobalId;
            internal int WorkerOwner;
            internal eChimps WorkerType;
            internal int TargetUnitId;
            internal int TargetGlobalId;
            internal int ReferenceDamage;
            internal int RemainingLifetimeMilliseconds;
        }

        private sealed class SavedSelection
        {
            internal long LeaseGeneration;
            internal int UnitId;
            internal int GlobalId;
            internal eChimps Type;
            internal int Owner;
            internal ushort OriginalCommandModeValue;
            internal ushort OriginalSelectionOwnerValue;
            internal int OriginalWorkLink;
            internal int OriginalTribeId;
            internal int OriginalX;
            internal int OriginalY;
            internal OccupancyProvenance Occupancy;
        }

        private readonly object _gate = new object();
        private readonly Action<string> _info;
        private readonly Action<string> _warning;
        private readonly Action<string> _error;
        private readonly Harmony _harmony;
        private readonly Dictionary<int, CommandState> _commands =
            new Dictionary<int, CommandState>();
        private readonly Dictionary<int, PendingDirectWorkCompletion>
            _pendingDirectWorkCompletions =
                new Dictionary<int, PendingDirectWorkCompletion>();
        private readonly Dictionary<int, PendingWorkResumptionProof>
            _pendingWorkResumptionProofs =
                new Dictionary<int, PendingWorkResumptionProof>();
        private readonly Dictionary<int, OwnedProjectile> _ownedProjectiles =
            new Dictionary<int, OwnedProjectile>();
        private readonly Queue<InputPacket> _inputPackets =
            new Queue<InputPacket>();
        private readonly HashSet<string> _evidenceLogged =
            new HashSet<string>(StringComparer.Ordinal);

        private IDisposable _mapStartSubscription;
        private IDisposable _mapUnloadSubscription;
        private IDisposable _projectileDamageSubscription;
        private IDisposable _projectileSpawnSubscription;
        private IDisposable _meleeDamageSubscription;
        private IDisposable _moveHereSubscription;
        private IDisposable _unitDeleteSubscription;
        private IDisposable _tribeMoveOrderSubscription;
        private IDisposable _tribeTargetOrderSubscription;
        // Tribe id the native commit gave our most recently confirmed
        // selection; kept after release purely as evidence so a native order
        // that arrives for that tribe after the engine already deselected the
        // worker is still attributable in the log.
        private int _lastConfirmedSelectionTribeId;
        private int _lastConfirmedSelectionUnitId;
        private int _animationProbesLogged;
        // Previous scan's tile per militia worker; only used to tell a walking
        // reference worker from a standing one in the animation probe.
        private int[] _cursorMoveBlock;
        private int[] _cursorAttackBlock;
        private int _cursorSamplesLogged;
        private int _cursorReplaysLogged;
        private int _commandClassEvidenceLogged;
        private readonly HashSet<string> _commandClassEvidenceContexts =
            new HashSet<string>(StringComparer.Ordinal);
        // Dichte Animationsspur: je Unity-Takt eine Zeile, gedeckelt. Die
        // 250-ms-Scansonde war zu grob, um zu sehen, WELCHES Feld sich beim
        // freien Laeufer bewegt und beim kommandierten nicht.
        private int _animationTraceLogged;
        private int _animationTraceCommandId;
        private long _animationTraceGeneration;
        // Im Scan (Hauptfaden) als unveraenderliche Werte-Snapshots gefuellt,
        // auf dem Engine-Faden nur gelesen. Das Cachen bloss der IDs reicht
        // nicht: deren Aufloesung waere erneut ein Extender-Aufruf aus dem
        // Run-Postfix.
        private Dictionary<int, ConeUnitSample> _measureMilitiaUnits =
            new Dictionary<int, ConeUnitSample>();
        private ConeUnitSample _measureSoldier;
        private long[] _measureOwnUnitTiles = Array.Empty<long>();
        private int _saveRestoreLogged;
        private int _hunterAnimationProbesLogged;
        // AI state the engine itself uses for a walking worker of a given
        // type, learned from uncommanded workers whose tile changed.
        private readonly Dictionary<eChimps, int> _observedWalkState =
            new Dictionary<eChimps, int>();
        private readonly Dictionary<eChimps, Dictionary<int, int>>
            _walkStateCounts =
                new Dictionary<eChimps, Dictionary<int, int>>();
        // The engine's walking SPRITE BASE (r_CurrentSpriteAnimationFrame, unit
        // +0x44) for a given worker type, learned exactly like the walk AI
        // state above. Measured 2026-08-29: a free-walking hunter carries base
        // 9, an idle/selected one base 1; the woodcutter carries 0 in both.
        // The per-unit update's commanded branch (CrusaderDE.dll 0x184AB4)
        // never writes +0x6A0, so once command_mode is held at 1 the base stays
        // frozen at its selection-time value - which for the hunter is the
        // crouch/idle base 1, producing "a crouching hunter that slides". The
        // frame within the set still advances through r_AnimationFrame, so
        // writing the walking base makes the commanded worker animate.
        private readonly Dictionary<eChimps, int> _observedWalkSprite =
            new Dictionary<eChimps, int>();
        private readonly Dictionary<eChimps, Dictionary<int, int>>
            _walkSpriteCounts =
                new Dictionary<eChimps, Dictionary<int, int>>();
        private readonly Dictionary<int, long> _previousWorkerPositions =
            new Dictionary<int, long>();
        private readonly Dictionary<int, int> _aiStateHistory =
            new Dictionary<int, int>();
        private int _aiTransitionsLogged;
        private int _archerProjectileProbesLogged;
        private int _naturalHunterProjectileProbesLogged;
        private int _commandedHunterProjectileProbesLogged;
        private int _lastArcherProjectileTick;
        private int _lastNaturalHunterProjectileTick;
        private int _lastCommandedHunterProjectileTick;
        private readonly long[] _scanDurationMicroseconds =
            new long[PerformanceWindowSamples];
        private int _scanDurationSampleCount;
        private int _performanceEvidenceLogged;
        private OwnedStackRowMutation<int> _woodcutterRow;
        private OwnedValueMutation<bool> _hunterHutAvailability;
        private MethodInfo _nativeInputTarget;
        private MethodInfo _nativeRunTarget;
        private MethodInfo _nativeSelectedTroopsTarget;
        private MethodInfo _troopsSelectedUiTarget;
        private MethodInfo _hunterHutCanPlaceTarget;
        private FieldInfo _nativeSelectionBoxField;
        private FieldInfo _nativeSelectionStartField;
        private FieldInfo _nativeSelectionCurrentField;
        private FieldInfo _nativeSelectedChimpListField;
        private FieldInfo _nativeLastSelectedChimpListField;
        private FieldInfo _nativeUnderCursorChimpListField;
        private FieldInfo _nativeGotNewSelectionInfoField;
        private FieldInfo _engineSelectedChimpsField;
        private int[] _engineSelectedChimpsBuffer;
        private bool _inputPatchApplied;
        private bool _nativeRunPatchApplied;
        private bool _nativeSelectedTroopsPatchApplied;
        private bool _troopsSelectedUiPatchApplied;
        private bool _hunterHutCanPlacePatchApplied;
        private bool _saveHandlerRegistered;
        private bool _prepared;
        private volatile bool _mapApplied;
        private volatile bool _networkSuppressed;
        private volatile bool _selectionQuarantineSuppressed;
        private bool _scanCensusLogged;
        private int _lastScanEnemyPairs = -1;
        private int _nextScanCensusLogTick;
        private int _selectedWorkerId;
        private int _nativeRunThreadId;
        private bool _insideNativeRunPostfix;
        private bool _boundarySelectionReleaseRequested;
        private string _boundarySelectionReleaseReason;
        private int _pendingSelectionWorkerId;
        private int _directClickGestureUnitId;
        private bool _confirmedSelectionGestureNoOp;
        private bool _nativeSelectionPacketInFlight;
        private bool _directSelectionMouseUpAccepted;
        private bool _pendingSelectionCancellationRequested;
        private bool _pendingSelectionIdentityInvalidated;
        private bool _nativeSelectionDisabledForProcess;
        private bool _nativeCommandClassUnavailableForProcess;
        private string _pendingSelectionCancellationReason;
        private NativeSelectionLifecycle _nativeSelectionLifecycle;
        private int _directSelectionDeadlineTick;
        private int _quarantineCleanSinceTick;
        private int _quarantineCleanRunCount;
        private int _internalMoveDepth;
        private int _internalMoveUnitId;
        private int _internalMoveTileX;
        private int _internalMoveTileY;
        private bool _internalMovePostObserved;
        private long _internalMoveReturnValue;
        private int _nativeMoveSequence;
        private int _nextScanTick;
        private long _uiEvidenceTickGeneration;
        private long _selectionLeaseGeneration;
        private long _commandGeneration;
        private long _commandClassLeaseGeneration;
        private long _nativeRunGeneration;
        private bool _insideNativeRunTransaction;
        private bool _hunterMoveStateReady;
        private bool _hunterMoveStateUnavailableForProcess;
        private long _rightClickGestureGeneration;
        private RightClickGesture _pendingRightClickGesture;
        private NativeSelectionLease _selectionLease;
        private List<SavedCommand> _pendingSavedCommands;
        private SavedSelection _pendingSavedSelection;
        private List<SavedOwnedProjectile> _pendingSavedProjectiles;
        private int _pendingSaveVersion;
        private Exception _deferredFailure;
        private SynchronizationContext _mainThreadContext;
        private int _mainThreadId;
        private bool _deferredRollbackRequested;
        private bool _deferredRollbackReady;
        private bool _deferredRollbackQueued;
        private readonly WorkerMilitiaNativeRevertQueue _commandClassRevertQueue =
            new WorkerMilitiaNativeRevertQueue();
        private IntPtr _nativeModuleBase;
        private WorkerMilitiaCommandClass _commandClass;
        private WorkerMilitiaHunterMoveState _hunterMoveState;
        private NativeUnitSelectionMarkerClear _nativeUnitSelectionMarkerClear;
        private NativePlayerSelectionClear _nativePlayerSelectionClear;

        internal WorkerMilitiaFeature(
            Harmony harmony,
            Action<string> info,
            Action<string> warning,
            Action<string> error)
        {
            _harmony = harmony ?? throw new ArgumentNullException("harmony");
            _info = info ?? throw new ArgumentNullException("info");
            _warning = warning ?? throw new ArgumentNullException("warning");
            _error = error ?? throw new ArgumentNullException("error");
        }

        public string Id
        {
            get { return "unit.worker_militia"; }
        }

        public IReadOnlyList<ExtensionLeaseClaim> ExclusiveClaims
        {
            get { return BuildClaims(WorkerMilitiaNativeLayout.Current); }
        }

        /// <summary>
        /// Managed claims plus the engine sites of the running build. The
        /// relocated census table, the command-target trampoline and the
        /// hunter cave live in the private WorkerMilitiaNativeArena page and
        /// need no claim; the engine instructions that jump there do.
        /// </summary>
        internal static ExtensionLeaseClaim[] BuildClaims(
            WorkerMilitiaNativeLayout layout)
        {
            var claims = new List<ExtensionLeaseClaim>(ManagedClaims);
            if (layout == null)
            {
                return claims.ToArray();
            }
            // The class adapter rewrites three instructions in this exact
            // census.
            claims.Add(EngineClaim(layout.CensusFunctionRva, 0));
            claims.Add(EngineClaim(layout.CensusWindowBaseRva, 0));
            claims.Add(EngineClaim(layout.CensusWindowLimitRva, 0));
            claims.Add(EngineClaim(layout.CensusCaseLookupRva, 0));
            // The same adapter owns the command-target chain: five bytes at
            // the "no commandable class selected" fallback. Without this
            // site the command-target routine answers -1 for a militia-only
            // selection and no cone can ever appear, however well the census
            // is taught.
            claims.Add(EngineClaim(layout.CommandTargetFallbackRva, 5));
            // Persistent for the feature lifetime: the native tribe executor
            // writes move state 0x65, which woodcutters understand but the
            // hunter FSM otherwise drops through its unknown-state cleanup.
            claims.Add(EngineClaim(layout.HunterFinalStateDispatchRva, 6));
            claims.Add(EngineClaim(layout.MoveHereRva, 0));
            claims.Add(EngineClaim(layout.UnitSelectionMarkerClearRva, 0));
            claims.Add(EngineClaim(layout.PlayerSelectionClearRva, 0));
            return claims.ToArray();
        }

        private static ExtensionLeaseClaim EngineClaim(int rva, int length)
        {
            return ExtensionLeaseClaim.Hook(
                "CrusaderDE.dll+0x"
                + rva.ToString("X", CultureInfo.InvariantCulture)
                + (length > 0
                    ? "[" + length.ToString(CultureInfo.InvariantCulture) + "]"
                    : string.Empty));
        }

        public bool Prepare(out string failure)
        {
            if (WorkerMilitiaNativeLayout.Current == null)
            {
                // Only the militia is bound to engine bytes; the rest of the
                // mod keeps running on an unknown CrusaderDE.dll.
                failure = "CrusaderDE.dll is not a build the militia knows "
                    + "(known: 2.80, 2.7)";
                return false;
            }
            int[] pinnedEnumValues =
            {
                (int)eChimps.CHIMP_TYPE_WOODCUTTER,
                (int)eChimps.CHIMP_TYPE_HUNTER,
                (int)eChimps.CHIMP_TYPE_MACEMAN,
                ValidTargetCount,
            };
            if (pinnedEnumValues[0] != 3
                || pinnedEnumValues[1] != 6
                || pinnedEnumValues[2] != 26
                || pinnedEnumValues[3] != 89
                || (int)eMappers.MAPPER_HUNTER != 78
                || Enum.GetValues(typeof(eChimps)).Length != ExpectedEnumCount)
            {
                failure = "pinned eChimps layout changed";
                return false;
            }
            if (!WorkerMilitiaPolicyIsSafe())
            {
                failure = "generated militia policy is outside its safe bounds";
                return false;
            }
            // SE 2.x names 0x30 r_UnitHover and 0xAE r_UnitSelected; SE 1.44
            // called them r_UnitSelected (UInt32) and r_UnitSelected2. The
            // engine reads +0x30 as a WORD (cmp word [unit+0x68C],0 in the
            // command-target routine), so the 2.x UInt16 model is the exact
            // one. Offsets, not names, are what this check pins.
            FieldInfo nativeSelectedField = typeof(GameUnit).GetField(
                "r_UnitHover",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo selectionBlockerField = typeof(GameUnit).GetField(
                "N0000019A",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo selectionAuxiliaryField = typeof(GameUnit).GetField(
                "N0000011E",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo selectionOwnerField = typeof(GameUnit).GetField(
                "r_UnitSelected",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo commandModeField = typeof(GameUnit).GetField(
                "N000000A7",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo aiStateField = typeof(GameUnit).GetField(
                "r_AIState",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo selectionRelevantField = typeof(GameUnit).GetField(
                "r_SelectionRelevant3",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo workerNameField = typeof(GameUnit).GetField(
                "N000000D0",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo hoveredCountField = typeof(GameUnitManager).GetField(
                "r_HoveredChimpsCount",
                BindingFlags.Public | BindingFlags.Instance);
            FieldInfo selectedCountField = typeof(GameUnitManager).GetField(
                "r_SelectedChimpsCount",
                BindingFlags.Public | BindingFlags.Instance);
            if (Marshal.SizeOf(typeof(GameUnit)) != NativeGameUnitSize
                || nativeSelectedField == null
                || nativeSelectedField.FieldType != typeof(ushort)
                || Marshal.OffsetOf(typeof(GameUnit), "r_UnitHover").ToInt32()
                    != NativeSelectedOffset
                || selectionAuxiliaryField == null
                || selectionAuxiliaryField.FieldType != typeof(ushort)
                || Marshal.OffsetOf(typeof(GameUnit), "N0000011E").ToInt32()
                    != NativeSelectionAuxiliaryOffset
                || selectionOwnerField == null
                || selectionOwnerField.FieldType != typeof(ushort)
                || Marshal.OffsetOf(
                    typeof(GameUnit),
                    "r_UnitSelected").ToInt32() != NativeSelectionOwnerOffset
                || selectionBlockerField == null
                || selectionBlockerField.FieldType != typeof(uint)
                || Marshal.OffsetOf(typeof(GameUnit), "N0000019A").ToInt32()
                    != NativeSelectionBlockerOffset
                || commandModeField == null
                || commandModeField.FieldType != typeof(ushort)
                || Marshal.OffsetOf(typeof(GameUnit), "N000000A7").ToInt32()
                    != NativeCommandModeOffset
                || aiStateField == null
                || aiStateField.FieldType != typeof(ushort)
                || Marshal.OffsetOf(typeof(GameUnit), "r_AIState").ToInt32()
                    != NativeAiStateOffset
                || selectionRelevantField == null
                || selectionRelevantField.FieldType != typeof(ushort)
                || Marshal.OffsetOf(
                    typeof(GameUnit),
                    "r_SelectionRelevant3").ToInt32()
                    != NativeSelectionRelevantOffset
                || workerNameField == null
                || workerNameField.FieldType != typeof(ushort)
                || Marshal.OffsetOf(typeof(GameUnit), "N000000D0").ToInt32()
                    != NativeWorkerNameOffset
                || hoveredCountField == null
                || hoveredCountField.FieldType != typeof(uint)
                || Marshal.OffsetOf(
                    typeof(GameUnitManager),
                    "r_HoveredChimpsCount").ToInt32()
                    != NativeHoveredCountOffset
                // SE 2.x models the per-player count array itself as a fixed
                // buffer at its base (0x24); the militia indexes it by player.
                || selectedCountField == null
                || Marshal.OffsetOf(
                    typeof(GameUnitManager),
                    "r_SelectedChimpsCount").ToInt32()
                    != NativeSelectedCountBaseOffset)
            {
                failure = "pinned GameUnit native-selection layout changed";
                return false;
            }
            if (!NativeFieldMatches(
                    typeof(GameUnit),
                    "r_AliveState",
                    typeof(AliveState),
                    NativeUnitAliveStateOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "r_UnitChimp",
                    typeof(eChimps),
                    NativeUnitTypeOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "r_ControllableForPlayerId",
                    typeof(byte),
                    NativeUnitOwnerOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "r_GlobalId",
                    typeof(uint),
                    NativeUnitGlobalIdOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "r_CurrentWorldPositionX",
                    typeof(ushort),
                    NativeUnitWorldPositionXOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "r_CurrentWorldPositionY",
                    typeof(ushort),
                    NativeUnitWorldPositionYOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "r_TribeId",
                    typeof(ushort),
                    NativeUnitTribeOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "r_LinkedProductionBuildingId",
                    typeof(ushort),
                    NativeUnitWorkLinkOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "N000000C5",
                    typeof(uint),
                    NativeUnitOccupancySlotContainerOffset)
                || NativeUnitOccupancySlotOffset
                    != NativeUnitOccupancySlotContainerOffset + sizeof(ushort)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "N000001D8",
                    typeof(uint),
                    NativeUnitOccupancyBuildingOffset)
                || !NativeFieldMatches(
                    typeof(GameUnit),
                    "N00000062",
                    typeof(ushort),
                    NativeCommandMarkerContainerOffset))
            {
                failure = "pinned GameUnit worker-occupancy layout changed";
                return false;
            }
            if (Marshal.SizeOf(typeof(GameBuilding)) != NativeGameBuildingSize
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_AliveState",
                    typeof(AliveState),
                    NativeBuildingAliveStateOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_BuildingType",
                    typeof(eStructs),
                    NativeBuildingTypeOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_PlayerIdOwner",
                    typeof(ushort),
                    NativeBuildingOwnerOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_GlobalId",
                    typeof(uint),
                    NativeBuildingGlobalIdOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_WorldPositionX",
                    typeof(ushort),
                    NativeBuildingWorldPositionXOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_WorldPositionY",
                    typeof(ushort),
                    NativeBuildingWorldPositionYOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_TotalWorkersRequired",
                    typeof(ushort),
                    NativeBuildingRequiredWorkersOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_TotalCurrentWorkers",
                    typeof(ushort),
                    NativeBuildingCurrentWorkersOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_TotalMissingWorkers",
                    typeof(ushort),
                    NativeBuildingMissingWorkersOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_WorkerId_1",
                    typeof(ushort),
                    NativeBuildingWorkerIdOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_WorkerId_2",
                    typeof(ushort),
                    NativeBuildingWorkerIdOffset + sizeof(ushort))
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_WorkerId_3",
                    typeof(ushort),
                    NativeBuildingWorkerIdOffset + 2 * sizeof(ushort))
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "r_WorkerId_4",
                    typeof(uint),
                    NativeBuildingWorkerIdOffset + 3 * sizeof(ushort))
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "N0000176A",
                    typeof(uint),
                    NativeBuildingWorkerGlobalIdOffset)
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "N000017F1",
                    typeof(uint),
                    NativeBuildingWorkerGlobalIdOffset + sizeof(uint))
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "N0000176B",
                    typeof(uint),
                    NativeBuildingWorkerGlobalIdOffset + 2 * sizeof(uint))
                || !NativeFieldMatches(
                    typeof(GameBuilding),
                    "N000017F3",
                    typeof(uint),
                    NativeBuildingWorkerGlobalIdOffset + 3 * sizeof(uint)))
            {
                failure = "pinned GameBuilding worker-occupancy layout changed";
                return false;
            }
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (units == null
                || GameBuildingManagerAPI.Instance == null
                || GamePlayerManagerAPI.Instance == null
                || GameProjectileManagerAPI.Instance == null)
            {
                failure = "unit, player or projectile API is unavailable";
                return false;
            }
            var maceman = new int[ValidTargetCount];
            for (int target = 0; target < maceman.Length; target++)
            {
                maceman[target] = units.GetMeleeDamageFromTo(
                    eChimps.CHIMP_TYPE_MACEMAN,
                    (eChimps)target);
            }
            // FromMacemanRow wirft bei einer unbrauchbaren Zeile - etwa wenn
            // die API fuer ein ungueltiges Zielpaar einen negativen Wert
            // liefert. Jede andere Pruefung in dieser Methode setzt statt
            // dessen 'failure' und gibt false zurueck; diese hier tat es nicht
            // und haette die Vorbereitung mit einer Ausnahme abgebrochen.
            try
            {
                WorkerMilitiaDamagePlan.FromMacemanRow(
                    maceman,
                    GeneratedWorkerMilitiaContract.DamageDivisor);
            }
            catch (Exception exception)
            {
                failure = "the maceman melee row is not usable as a militia "
                    + "damage source (" + exception.GetType().Name + ": "
                    + exception.Message + ")";
                return false;
            }
            _nativeModuleBase = FindNativeModuleBase();
            if (_nativeModuleBase == IntPtr.Zero)
            {
                failure = "pinned CrusaderDE native module is not loaded";
                return false;
            }
            _nativeUnitSelectionMarkerClear =
                (NativeUnitSelectionMarkerClear)Marshal.GetDelegateForFunctionPointer(
                    new IntPtr(
                        _nativeModuleBase.ToInt64()
                            + NativeUnitSelectionMarkerClearRva),
                    typeof(NativeUnitSelectionMarkerClear));
            _nativePlayerSelectionClear =
                (NativePlayerSelectionClear)Marshal.GetDelegateForFunctionPointer(
                    new IntPtr(
                        _nativeModuleBase.ToInt64()
                            + NativePlayerSelectionClearRva),
                    typeof(NativePlayerSelectionClear));
            _nativeInputTarget = FindNativeInputTarget();
            _nativeRunTarget = FindNativeRunTarget();
            _nativeSelectedTroopsTarget = FindNativeSelectedTroopsTarget();
            _troopsSelectedUiTarget = FindTroopsSelectedUiTarget();
            _hunterHutCanPlaceTarget = FindHunterHutCanPlaceTarget();
            _nativeSelectionBoxField = FindNativeSelectionBoxField();
            _nativeSelectionStartField = FindNativeField(
                "troopSelectMouseStart",
                typeof(UnityEngine.Vector2));
            _nativeSelectionCurrentField = FindNativeField(
                "troopSelectMouseCurrent",
                typeof(UnityEngine.Vector2));
            _nativeSelectedChimpListField = FindNativeField(
                "selectedChimpList",
                typeof(int[]));
            _nativeLastSelectedChimpListField = FindNativeField(
                "lastSelectedChimpList",
                typeof(int[]));
            _nativeUnderCursorChimpListField = FindNativeField(
                "underCursorChimpList",
                typeof(int[]));
            _nativeGotNewSelectionInfoField = FindNativeField(
                "gotNewSelectionInfo",
                typeof(bool));
            _engineSelectedChimpsField = typeof(EngineInterface).GetField(
                "selectedChimps",
                BindingFlags.NonPublic
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly);
            if (_engineSelectedChimpsField == null
                || _engineSelectedChimpsField.FieldType != typeof(int[]))
            {
                failure =
                    "exact EngineInterface.selectedChimps pair buffer is unavailable";
                return false;
            }
            _engineSelectedChimpsBuffer =
                _engineSelectedChimpsField.GetValue(null) as int[];
            if (_engineSelectedChimpsBuffer == null
                || _engineSelectedChimpsBuffer.Length
                    != NativeSelectedPairBufferLength)
            {
                failure =
                    "EngineInterface.selectedChimps is not the pinned 20000-int pair buffer";
                return false;
            }
            _prepared = true;
            failure = null;
            return true;
        }

        private static bool NativeFieldMatches(
            Type nativeType,
            string fieldName,
            Type fieldType,
            int offset)
        {
            FieldInfo field = nativeType.GetField(
                fieldName,
                BindingFlags.Public | BindingFlags.Instance);
            return field != null
                && field.FieldType == fieldType
                && Marshal.OffsetOf(nativeType, fieldName).ToInt32() == offset;
        }

        public void Apply()
        {
            if (!_prepared)
            {
                throw new InvalidOperationException(
                    "Worker militia was not prepared before apply");
            }
            Observable<MapStartEventArgs> mapStart =
                MapLoaderR3EventHooks.OnStartMap.Observable;
            Observable<MapUnloadEventArgs> mapUnload =
                MapLoaderR3EventHooks.OnUnloadMap.Observable;
            Observable<UnitTakeDamageByProjectileExEventArgs> projectileDamage =
                UnitR3EventHooks.OnUnitTakeProjectileDamageEx.Observable;
            Observable<UnitTakeDamageByMeleeEventArgs> meleeDamage =
                UnitR3EventHooks.OnUnitTakeMeleeDamage.Observable;
            Observable<UnitMoveHereEventArgs> moveHere =
                UnitR3EventHooks.OnUnitMoveHere.Observable;
            Observable<UnitDeleteEventArgs> unitDelete =
                UnitR3EventHooks.OnUnitDelete.Observable;
            Observable<TribeIssueOrderMoveHereEventArgs> tribeMoveOrder =
                TribeR3EventHooks.OnTribeIssueOrderMoveHere.Observable;
            Observable<TribeIssueOrderWithTargetEventArgs> tribeTargetOrder =
                TribeR3EventHooks.OnTribeIssueOrderWithTarget.Observable;
            if (mapStart == null || mapUnload == null
                || projectileDamage == null || meleeDamage == null
                || moveHere == null || unitDelete == null
                || tribeMoveOrder == null || tribeTargetOrder == null)
            {
                throw new InvalidOperationException(
                    "Worker militia event streams are unavailable");
            }
            _mainThreadContext = SynchronizationContext.Current;
            if (_mainThreadContext == null)
            {
                throw new InvalidOperationException(
                    "Worker militia requires the Unity main-thread context");
            }
            _mainThreadId = Thread.CurrentThread.ManagedThreadId;

            InstallNativeInputPatch();
            if (!ModSaveDataAPI.Instance.RegisterModDataHandler(
                    SaveDataIdentifier,
                    SaveMilitiaData,
                    LoadMilitiaData))
            {
                RemoveNativeInputPatch();
                throw new InvalidOperationException(
                    "Worker militia save-data identifier is already registered");
            }
            _saveHandlerRegistered = true;
            _mapStartSubscription =
                ObservableSubscribeExtensions.Subscribe(mapStart, OnStartMap);
            _mapUnloadSubscription =
                ObservableSubscribeExtensions.Subscribe(mapUnload, OnUnloadMap);
            _projectileDamageSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    projectileDamage,
                    OnProjectileDamage);
            Observable<ProjectileSpawnEventArgs> projectileSpawn =
                ProjectileR3EventHooks.OnProjectileSpawn.Observable;
            if (projectileSpawn != null)
            {
                _projectileSpawnSubscription =
                    ObservableSubscribeExtensions.Subscribe(
                        projectileSpawn,
                        OnProjectileSpawnObserved);
            }
            _meleeDamageSubscription =
                ObservableSubscribeExtensions.Subscribe(meleeDamage, OnMeleeDamage);
            _moveHereSubscription =
                ObservableSubscribeExtensions.Subscribe(moveHere, OnMoveHere);
            _unitDeleteSubscription =
                ObservableSubscribeExtensions.Subscribe(unitDelete, OnUnitDelete);
            _tribeMoveOrderSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    tribeMoveOrder,
                    OnTribeMoveOrder);
            _tribeTargetOrderSubscription =
                ObservableSubscribeExtensions.Subscribe(
                    tribeTargetOrder,
                    OnTribeTargetOrder);
            _hunterMoveState = new WorkerMilitiaHunterMoveState(
                _info,
                _warning);
            InitializeCommandClass();
        }

        /// <summary>
        /// Prepares the native selection-class adapter without changing native
        /// memory. The patch itself is opened only by an exact selection lease.
        /// </summary>
        /// <remarks>
        /// Construction is side-effect free. Fingerprint and code-byte checks
        /// remain in <see cref="WorkerMilitiaCommandClass.TryApply"/> and run at
        /// the last safe moment, after identity/workplace proof and before the
        /// command-mode mutation of that same direct-click transaction.
        /// </remarks>
        private void InitializeCommandClass()
        {
            _commandClass = new WorkerMilitiaCommandClass(_info, _warning);
        }

        private bool HunterMoveStateNeedsRevertLocked()
        {
            return _hunterMoveState != null
                && (_hunterMoveState.IsApplied
                    || _hunterMoveState.IsIndeterminate);
        }

        /// <summary>
        /// Opens the persistent hunter move-state adapter on the one native
        /// run thread before an operational map can process militia input.
        /// </summary>
        private bool EnsureHunterMoveStateBeforeNativeRunLocked()
        {
            if (_hunterMoveStateReady
                && _hunterMoveState != null
                && _hunterMoveState.IsApplied
                && !_hunterMoveState.IsIndeterminate)
            {
                return true;
            }
            if (_hunterMoveStateUnavailableForProcess)
            {
                return false;
            }
            if (_hunterMoveState == null)
            {
                _hunterMoveStateUnavailableForProcess = true;
                _error(
                    "Worker militia cannot activate because the native hunter "
                    + "move-state adapter is unavailable.");
                return false;
            }
            bool applied;
            string reason;
            try
            {
                applied = _hunterMoveState.TryApply(
                    _nativeModuleBase,
                    _nativeRunThreadId,
                    out reason);
            }
            catch (Exception exception)
            {
                applied = false;
                reason = exception.GetType().Name + ": " + exception.Message;
            }
            if (applied)
            {
                _hunterMoveStateReady = true;
                return true;
            }
            _hunterMoveStateReady = false;
            _hunterMoveStateUnavailableForProcess = true;
            _nativeSelectionDisabledForProcess = true;
            _error(
                "Worker militia remains inert because the pinned native "
                + "hunter move-state transaction was refused: "
                + (reason ?? "unknown reason") + ". No half-working movement "
                + "fallback is enabled.");
            return false;
        }

        private bool TryRevertHunterMoveStateAtNativeBoundaryLocked(
            string why)
        {
            if (!HunterMoveStateNeedsRevertLocked())
            {
                _hunterMoveStateReady = false;
                return true;
            }
            if (!_insideNativeRunPostfix
                || Thread.CurrentThread.ManagedThreadId != _nativeRunThreadId)
            {
                return false;
            }
            string reason;
            bool reverted;
            try
            {
                reverted = _hunterMoveState.TryRevert(why, out reason);
            }
            catch (Exception exception)
            {
                reverted = false;
                reason = exception.GetType().Name + ": " + exception.Message;
            }
            if (!reverted)
            {
                _hunterMoveStateUnavailableForProcess = true;
                _error(
                    "Worker militia cannot prove restoration of its native "
                    + "hunter move-state patch: "
                    + (reason ?? "unknown readback failure") + ".");
                return false;
            }
            _hunterMoveStateReady = false;
            return true;
        }

        private bool TryBeginCommandClassLease(
            NativeSelectionLease lease,
            out string reason)
        {
            reason = null;
            if (lease == null || lease.Generation <= 0)
            {
                reason = "selection lease is absent or ungenerated";
                return false;
            }
            if (_nativeCommandClassUnavailableForProcess)
            {
                reason = "native selection-class patch is permanently unavailable";
                return false;
            }
            if (_commandClass == null)
            {
                reason = "selection-class adapter is unavailable";
                return false;
            }
            if (_commandClassRevertQueue.Pending)
            {
                reason = "a previous selection-class release awaits the native "
                    + "engine boundary";
                return false;
            }
            int currentThreadId = Thread.CurrentThread.ManagedThreadId;
            if (!_insideNativeRunTransaction
                || _nativeRunGeneration <= 0
                || (_nativeRunThreadId > 0
                    && currentThreadId != _nativeRunThreadId)
                || (_mainThreadId > 0 && currentThreadId == _mainThreadId))
            {
                reason = "selection-class transaction changed engine thread";
                return false;
            }
            if (_commandClassLeaseGeneration != 0)
            {
                if (_commandClassLeaseGeneration == lease.Generation
                    && lease.CommandClassApplied
                    && lease.CommandClassThreadId == currentThreadId
                    && lease.CommandClassRunGeneration > 0
                    && lease.CommandClassRunGeneration <= _nativeRunGeneration
                    && _commandClass.IsApplied)
                {
                    return true;
                }
                reason = "another selection generation owns the class patch";
                return false;
            }
            bool applied;
            try
            {
                applied = _commandClass.TryApply(_nativeModuleBase, out reason);
            }
            catch (Exception exception)
            {
                applied = false;
                reason = exception.GetType().Name + ": " + exception.Message;
            }
            if (applied)
            {
                lease.CommandClassApplied = true;
                lease.CommandClassThreadId = currentThreadId;
                lease.CommandClassRunGeneration = _nativeRunGeneration;
                _commandClassLeaseGeneration = lease.Generation;
                return true;
            }
            _nativeCommandClassUnavailableForProcess = true;
            _nativeSelectionDisabledForProcess = true;
            string failureKind = _commandClass.IsIndeterminate
                ? "native state is indeterminate and original-byte ownership "
                    + "is retained"
                : "the pinned patch transaction was refused";
            _error(
                "Worker militia permanently disabled native worker selection "
                + "for this process because " + failureKind + ": "
                + (reason ?? "unknown reason") + ".");
            return false;
        }

        private void EndCommandClassLease(
            NativeSelectionLease lease,
            string why)
        {
            if (lease == null || !lease.CommandClassApplied)
            {
                return;
            }
            if (_commandClassLeaseGeneration != lease.Generation)
            {
                _warning(
                    "Worker militia detected a class-patch generation mismatch "
                    + "while releasing selection; the patch is reverted "
                    + "fail-closed before any later unit can be selected.");
                _nativeSelectionDisabledForProcess = true;
                if (!_nativeCommandClassUnavailableForProcess)
                {
                    _selectionQuarantineSuppressed = true;
                }
            }
            RequestCommandClassRevertLocked(
                "selection lease "
                    + lease.Generation.ToString(CultureInfo.InvariantCulture)
                    + " ended: " + why);
            if (!_commandClassRevertQueue.Pending
                && !CommandClassNeedsRevertLocked())
            {
                ClearCommandClassLeaseOwnershipLocked(lease);
            }
        }

        private bool CommandClassNeedsRevertLocked()
        {
            return _commandClass != null
                && (_commandClass.IsApplied || _commandClass.IsIndeterminate);
        }

        private void RequestCommandClassRevertLocked(string why)
        {
            if (!CommandClassNeedsRevertLocked())
            {
                _commandClassRevertQueue.Complete();
                ClearCommandClassLeaseOwnershipLocked(null);
                return;
            }
            _commandClassRevertQueue.Request(why);
            TryCompleteQueuedCommandClassRevertLocked();
        }

        private bool TryCompleteQueuedCommandClassRevertLocked()
        {
            int currentThreadId = Thread.CurrentThread.ManagedThreadId;
            if (!_commandClassRevertQueue.TryGetAtNativeBoundary(
                    _insideNativeRunTransaction,
                    currentThreadId,
                    _nativeRunThreadId,
                    _mainThreadId,
                    out string why))
            {
                return false;
            }
            if (!_commandClass.TryRevert(why, out string failure))
            {
                _nativeCommandClassUnavailableForProcess = true;
                _nativeSelectionDisabledForProcess = true;
                _error(
                    "Worker militia cannot prove restoration of its native "
                    + "selection-class patch: "
                    + (failure ?? "unknown restore/readback failure") + ".");
                return false;
            }
            _commandClassRevertQueue.Complete();
            ClearCommandClassLeaseOwnershipLocked(null);
            return true;
        }

        private void ClearCommandClassLeaseOwnershipLocked(
            NativeSelectionLease additionalLease)
        {
            _commandClassLeaseGeneration = 0;
            if (_selectionLease != null)
            {
                _selectionLease.CommandClassApplied = false;
                _selectionLease.CommandClassThreadId = 0;
                _selectionLease.CommandClassRunGeneration = 0;
            }
            if (additionalLease != null
                && !ReferenceEquals(additionalLease, _selectionLease))
            {
                additionalLease.CommandClassApplied = false;
                additionalLease.CommandClassThreadId = 0;
                additionalLease.CommandClassRunGeneration = 0;
            }
        }

        /// <summary>
        /// Closes the native class window before the next census if its exact
        /// identity-bound owner disappeared or changed.
        /// </summary>
        /// <remarks>
        /// This is deliberately a prefix of EngineInterface.run: reverting in
        /// the postfix would let one foreign/reused unit pass through the
        /// widened type table for a full native tick.
        /// </remarks>
        private bool ValidateCommandClassLeaseBeforeNativeRun()
        {
            lock (_gate)
            {
                int currentThreadId = Thread.CurrentThread.ManagedThreadId;
                if (_insideNativeRunTransaction)
                {
                    FailCommandClassLeaseLocked(
                        "nested native-run transaction",
                        true,
                        true);
                    return !_commandClassRevertQueue.Pending
                        && !CommandClassNeedsRevertLocked();
                }
                _insideNativeRunTransaction = true;
                _nativeRunGeneration = _nativeRunGeneration == long.MaxValue
                    ? 1
                    : _nativeRunGeneration + 1;
                if (_nativeRunThreadId == 0)
                {
                    _nativeRunThreadId = currentThreadId;
                }
                if (_mapApplied && !_networkSuppressed)
                {
                    // Operation remains gated by _hunterMoveStateReady. A
                    // failed pin never blocks the engine's own run; it only
                    // leaves this feature inert and fully diagnosable.
                    EnsureHunterMoveStateBeforeNativeRunLocked();
                }
                if (_commandClassRevertQueue.Pending)
                {
                    TryCompleteQueuedCommandClassRevertLocked();
                    if (_commandClassRevertQueue.Pending)
                    {
                        return false;
                    }
                }
                if (_commandClassLeaseGeneration == 0)
                {
                    return !CommandClassNeedsRevertLocked();
                }

                NativeSelectionLease lease = _selectionLease;
                string failure = null;
                bool identityInvalidated = false;
                bool internalContradiction = false;
                if (lease == null)
                {
                    failure = "class patch has no selection lease";
                    identityInvalidated = true;
                    internalContradiction = true;
                }
                else if (_commandClassLeaseGeneration != lease.Generation
                    || !lease.CommandClassApplied
                    || _commandClass == null
                    || !_commandClass.IsApplied
                    || _commandClass.IsIndeterminate)
                {
                    failure = "class patch generation/ownership disagrees";
                    identityInvalidated = true;
                    internalContradiction = true;
                }
                else if (lease.CommandClassThreadId != currentThreadId
                    || _nativeRunThreadId != currentThreadId
                    || lease.CommandClassRunGeneration <= 0
                    || lease.CommandClassRunGeneration > _nativeRunGeneration
                    || (_mainThreadId > 0 && currentThreadId == _mainThreadId))
                {
                    failure = "class patch crossed its native-run thread";
                    identityInvalidated = true;
                    internalContradiction = true;
                }
                else
                {
                    bool pendingLifecycle = _pendingSelectionWorkerId
                            == lease.UnitId
                        && (_nativeSelectionLifecycle
                                == NativeSelectionLifecycle.PacketInjected
                            || _nativeSelectionLifecycle
                                == NativeSelectionLifecycle.AwaitingCommit);
                    bool confirmedLifecycle = _pendingSelectionWorkerId == 0
                        && _selectedWorkerId == lease.UnitId
                        && _nativeSelectionLifecycle
                            == NativeSelectionLifecycle.Confirmed;
                    if (!pendingLifecycle && !confirmedLifecycle)
                    {
                        failure = "selection lifecycle no longer owns class lease";
                        identityInvalidated = true;
                        internalContradiction = true;
                    }
                }
                if (failure == null)
                {
                    if (GameUnitManagerAPI.Instance == null
                        || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                            lease.UnitId,
                            out var pointer))
                    {
                        failure = "class-lease unit no longer exists";
                        identityInvalidated = true;
                    }
                    else
                    {
                        ref GameUnit unit = ref pointer.AsRef();
                        int localPlayer = GamePlayerManagerAPI.Instance == null
                            ? 0
                            : GamePlayerManagerAPI.Instance.GetLocalPlayerId();
                        if (!SelectionLeaseIdentityMatches(lease, ref unit))
                        {
                            failure = "class-lease unit died or changed "
                                + "identity/owner/type";
                            identityInvalidated = true;
                        }
                        else if (localPlayer < 1
                            || localPlayer > 8
                            || lease.Owner != localPlayer)
                        {
                            failure = "local player no longer owns the class lease";
                        }
                        else if (SeInteropFieldAliases.CommandMode(ref unit) != 1)
                        {
                            failure = "worker command mode changed outside its lease";
                        }
                        else if (!WorkerOccupancyMatches(
                                lease.UnitId,
                                lease.GlobalId,
                                lease.Owner,
                                lease.Type,
                                lease.Occupancy))
                        {
                            failure = "worker workplace occupancy changed";
                            CommandState command;
                            if (_commands.TryGetValue(lease.UnitId, out command)
                                && command.WorkerGlobalId == lease.GlobalId
                                && command.WorkerOwner == lease.Owner
                                && command.WorkerType == lease.Type)
                            {
                                NoteWorkplaceLoss(command);
                                UnitSnapshot worker = CaptureUnit(lease.UnitId);
                                if (command.WorkplaceLost && worker != null)
                                {
                                    CompleteDirectWork(
                                        command,
                                        worker,
                                        "workplace_lost_before_native_census",
                                        false);
                                }
                            }
                        }
                    }
                }
                if (failure == null)
                {
                    return true;
                }
                FailCommandClassLeaseLocked(
                    failure,
                    identityInvalidated,
                    internalContradiction);
                return !_commandClassRevertQueue.Pending
                    && !CommandClassNeedsRevertLocked();
            }
        }

        private void FailCommandClassLeaseLocked(
            string failure,
            bool identityInvalidated,
            bool internalContradiction)
        {
            NativeSelectionLease lease = _selectionLease;
            if (lease != null && lease.CommandClassApplied)
            {
                EndCommandClassLease(lease, failure);
            }
            else
            {
                RequestCommandClassRevertLocked(failure);
            }
            if (internalContradiction)
            {
                _nativeCommandClassUnavailableForProcess = true;
                _nativeSelectionDisabledForProcess = true;
            }
            if (_pendingSelectionWorkerId > 0)
            {
                _pendingSelectionCancellationRequested = true;
                _pendingSelectionIdentityInvalidated |= identityInvalidated;
                _nativeSelectionDisabledForProcess |= identityInvalidated;
                if (identityInvalidated
                    && !_nativeCommandClassUnavailableForProcess)
                {
                    _selectionQuarantineSuppressed = true;
                }
                _pendingSelectionCancellationReason = failure;
                _nativeSelectionLifecycle = NativeSelectionLifecycle.Quarantined;
            }
            else
            {
                RequestSelectionReleaseAtNativeBoundary(failure);
            }
            string key = "command_class_fail_closed." + failure;
            if (_evidenceLogged.Add(key))
            {
                Action<string> log = internalContradiction ? _error : _warning;
                log(
                    "Worker militia closed the exact native command-class "
                    + "lease before another census: " + failure
                    + " internal_contradiction="
                    + TelemetryBoolean(internalContradiction) + ".");
            }
        }

        private void EndNativeRunTransaction()
        {
            lock (_gate)
            {
                _insideNativeRunTransaction = false;
            }
        }

        public void Tick()
        {
            long uiEvidenceTickGeneration;
            lock (_gate)
            {
                _uiEvidenceTickGeneration++;
                uiEvidenceTickGeneration = _uiEvidenceTickGeneration;
            }
            VerifyPendingMilitiaUiEvidence(uiEvidenceTickGeneration);
            LogAnimationTrace();

            bool completeDeferredRollback;
            lock (_gate)
            {
                completeDeferredRollback = _deferredRollbackRequested
                    && _deferredRollbackReady
                    && _pendingSelectionWorkerId <= 0
                    && _pendingDirectWorkCompletions.Count == 0
                    && _commands.Count == 0
                    && _selectionLease == null
                    && !_boundarySelectionReleaseRequested
                    && !_commandClassRevertQueue.Pending
                    && !CommandClassNeedsRevertLocked()
                    && !HunterMoveStateNeedsRevertLocked();
            }
            if (completeDeferredRollback)
            {
                CompleteDeferredRollbackAtSafeBoundary();
                return;
            }
            lock (_gate)
            {
                ThrowDeferredFailure();
                if (!IsOperationalLocked())
                {
                    _inputPackets.Clear();
                    _pendingRightClickGesture = null;
                    return;
                }
                int now = SimulationNowMilliseconds();
                DiscardExpiredRightClickGesture(now);
                ExpireWorkResumptionProofs(now);
                ExpireOwnedProjectiles(now);
                ProcessNativeInput();
                if (HasReached(now, _nextScanTick))
                {
                    _nextScanTick = unchecked(
                        now + GeneratedWorkerMilitiaContract.ScanIntervalMilliseconds);
                    long scanStarted = Stopwatch.GetTimestamp();
                    ScanAndAdvance(now);
                    RecordScanDuration(scanStarted);
                }
                ThrowDeferredFailure();
            }
        }

        public void RollbackOwned()
        {
            IDisposable[] subscriptions;
            lock (_gate)
            {
                _pendingWorkResumptionProofs.Clear();
                _ownedProjectiles.Clear();
                RequestCommandClassRevertLocked("feature rollback");
                bool nativeCleanupOutstanding =
                    _pendingSelectionWorkerId > 0
                    || _selectionLease != null
                    || _commands.Count > 0
                    || _pendingDirectWorkCompletions.Count > 0
                    || _boundarySelectionReleaseRequested
                    || _commandClassRevertQueue.Pending
                    || CommandClassNeedsRevertLocked()
                    || HunterMoveStateNeedsRevertLocked();
                if (nativeCleanupOutstanding)
                {
                    bool pendingReturnMove = _mapApplied;
                    _deferredRollbackRequested = true;
                    _deferredRollbackReady = false;
                    if (_pendingSelectionWorkerId > 0
                        && _selectionLease != null)
                    {
                        RequestOutstandingSelectionCancellation(
                            "feature rollback while native selection was pending",
                            false,
                            true);
                    }
                    _inputPackets.Clear();
                    _pendingRightClickGesture = null;
                    _mapApplied = false;
                    _networkSuppressed = true;
                    if (_pendingSelectionWorkerId > 0)
                    {
                        ReturnAllOtherCommandsToWork(
                            _pendingSelectionWorkerId,
                            "deferred feature rollback",
                            pendingReturnMove);
                    }
                    else
                    {
                        ReturnAllToWork(
                            "deferred feature rollback",
                            pendingReturnMove);
                        RequestSelectionReleaseAtNativeBoundary(
                            "deferred feature rollback");
                    }
                    RollbackWoodcutterRow("deferred feature rollback");
                    RollbackHunterHutAvailability(
                        "deferred feature rollback");
                    _error(
                        "Worker militia deferred native-hook rollback because "
                        + "native command/selection cleanup is still pending; "
                        + "the observer remains installed fail-closed.");
                    return;
                }
                subscriptions = new[]
                {
                    _tribeTargetOrderSubscription,
                    _tribeMoveOrderSubscription,
                    _unitDeleteSubscription,
                    _moveHereSubscription,
                    _meleeDamageSubscription,
                    _projectileDamageSubscription,
                    _projectileSpawnSubscription,
                    _mapUnloadSubscription,
                    _mapStartSubscription,
                };
                _tribeTargetOrderSubscription = null;
                _tribeMoveOrderSubscription = null;
                _meleeDamageSubscription = null;
                _moveHereSubscription = null;
                _unitDeleteSubscription = null;
                _projectileDamageSubscription = null;
                _projectileSpawnSubscription = null;
                _mapUnloadSubscription = null;
                _mapStartSubscription = null;
            }
            foreach (IDisposable subscription in subscriptions)
            {
                Dispose(subscription);
            }
            lock (_gate)
            {
                if (_commands.Count > 0
                    || _pendingDirectWorkCompletions.Count > 0
                    || _selectionLease != null
                    || _boundarySelectionReleaseRequested
                    || _commandClassRevertQueue.Pending
                    || CommandClassNeedsRevertLocked()
                    || HunterMoveStateNeedsRevertLocked())
                {
                    throw new InvalidOperationException(
                        "Worker militia host rollback crossed an unsettled "
                        + "native run-boundary cleanup");
                }
                RollbackWoodcutterRow("feature rollback");
                RollbackHunterHutAvailability("feature rollback");
                _selectedWorkerId = 0;
                _pendingSelectionWorkerId = 0;
                _inputPackets.Clear();
                _pendingRightClickGesture = null;
                _mapApplied = false;
                _networkSuppressed = false;
                _selectionQuarantineSuppressed = false;
            }
            if (_saveHandlerRegistered)
            {
                _saveHandlerRegistered = false;
                ModSaveDataAPI.Instance.UnregisterModDataHandler(
                    SaveDataIdentifier);
            }
            RemoveNativeInputPatch();
            lock (_gate)
            {
                _deferredRollbackRequested = false;
                _deferredRollbackReady = false;
                _deferredRollbackQueued = false;
                _pendingDirectWorkCompletions.Clear();
                _pendingWorkResumptionProofs.Clear();
                _ownedProjectiles.Clear();
                _boundarySelectionReleaseRequested = false;
                _boundarySelectionReleaseReason = null;
                _mainThreadContext = null;
                _mainThreadId = 0;
                _nativeRunThreadId = 0;
                _nativeRunGeneration = 0;
                _insideNativeRunTransaction = false;
                _insideNativeRunPostfix = false;
                _hunterMoveStateReady = false;
            }
        }

        /// <summary>
        /// Lifts a selection quarantine at a map boundary, but only once
        /// nothing from the quarantined session can still commit.
        /// </summary>
        /// <remarks>
        /// The quarantine exists because chore 0x48 has no proved cancellation
        /// primitive: while a selection packet is outstanding, a second worker
        /// must not take ownership. The rule the direct-click path states for
        /// releasing it is "the old chore has either committed and been removed
        /// or the process/**map** has been abandoned" - but nothing ever cleared
        /// the flag, not even on a map change. One identity mismatch therefore
        /// disabled selection, commands and combat for the rest of the session,
        /// across every map, until the game was restarted. That is exactly the
        /// symptom the owner reported as "the workers cannot be selected any
        /// more", and it is why the mod felt unreliable rather than broken.
        ///
        /// The safety property is kept: the lift only happens when no selection
        /// is pending and no packet is in flight, i.e. when there is no
        /// outstanding chore left to commit. If either is still true the
        /// quarantine stands and the map-start path takes its disabled branch
        /// exactly as before. Called under _gate.
        /// </remarks>
        private bool TryLiftSelectionQuarantineLocked()
        {
            if (!_nativeSelectionDisabledForProcess)
            {
                return false;
            }
            if (_nativeCommandClassUnavailableForProcess)
            {
                return false;
            }
            if (_pendingSelectionWorkerId > 0 || _nativeSelectionPacketInFlight)
            {
                return false;
            }
            string previous = _pendingSelectionCancellationReason ?? "unknown";
            _selectionQuarantineSuppressed = false;
            _nativeSelectionDisabledForProcess = false;
            _pendingSelectionIdentityInvalidated = false;
            _pendingSelectionCancellationRequested = false;
            _pendingSelectionCancellationReason = null;
            _nativeSelectionLifecycle = NativeSelectionLifecycle.Idle;
            _quarantineCleanSinceTick = 0;
            _quarantineCleanRunCount = 0;
            _warning(
                "Worker militia lifted its native-selection quarantine at a map "
                + "boundary (it was raised by: " + previous
                + "). No selection was pending and no packet was in flight, so "
                + "no chore from the quarantined session can still commit. "
                + "Workers are selectable again on this map.");
            return true;
        }

        private bool TryLiftSelectionQuarantineInMapLocked(int[] selected)
        {
            if (!_nativeSelectionDisabledForProcess)
            {
                return false;
            }
            if (_nativeCommandClassUnavailableForProcess)
            {
                return false;
            }
            int selectedCount = GetPinnedNativeSelectedCount();
            bool cleanAuthoritativeOutput = selectedCount == 0
                && selected != null
                && selected.Length == 0;
            bool noOwnedWorkOutstanding = _pendingSelectionWorkerId <= 0
                && !_nativeSelectionPacketInFlight
                && _selectionLease == null
                && _pendingRightClickGesture == null
                && !_pendingSelectionCancellationRequested;
            if (!cleanAuthoritativeOutput || !noOwnedWorkOutstanding)
            {
                _quarantineCleanSinceTick = 0;
                _quarantineCleanRunCount = 0;
                return false;
            }
            int now = SimulationNowMilliseconds();
            if (_quarantineCleanRunCount == 0)
            {
                _quarantineCleanSinceTick = now;
            }
            _quarantineCleanRunCount++;
            bool graceElapsed = HasReached(
                now,
                unchecked(
                    _quarantineCleanSinceTick
                    + SelectionQuarantineGraceMilliseconds));
            if (!WorkerMilitiaSafetyRules.CanLiftSelectionQuarantine(
                    _nativeSelectionDisabledForProcess,
                    _nativeCommandClassUnavailableForProcess,
                    cleanAuthoritativeOutput,
                    noOwnedWorkOutstanding,
                    _quarantineCleanRunCount,
                    graceElapsed,
                    SelectionQuarantineCleanRunFloor))
            {
                return false;
            }
            RearmAfterSelectionQuarantineLocked();
            _nativeSelectionDisabledForProcess = false;
            _pendingSelectionIdentityInvalidated = false;
            _pendingSelectionCancellationRequested = false;
            _pendingSelectionCancellationReason = null;
            _nativeSelectionLifecycle = NativeSelectionLifecycle.Idle;
            _quarantineCleanSinceTick = 0;
            _quarantineCleanRunCount = 0;
            _warning(RuntimeLogContract.WorkerMilitiaQuarantineRecoveredEvidence(
                "same_map",
                "authoritative_clean_window"));
            return true;
        }

        private void RearmAfterSelectionQuarantineLocked()
        {
            if (!_selectionQuarantineSuppressed)
            {
                return;
            }
            // A cross-map quarantine rolled the combat table back and delayed
            // save restore. Re-arm those owned pieces before reopening the
            // operational gate. A network map may observe/settle quarantine,
            // but it must never re-enable combat.
            if (_mapApplied && !_networkSuppressed)
            {
                ApplyWoodcutterRow();
                RestorePendingSaveData();
            }
            _selectionQuarantineSuppressed = false;
        }

        private void OnStartMap(MapStartEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Post)
            {
                return;
            }
            bool networked;
            bool localHost = true;
            int activePlayers = -1;
            int otherHumanPlayers = -1;
            try
            {
                networked = GameNetworkAPI.IsNetworkedEnvironment();
                if (networked)
                {
                    localHost = GameNetworkAPI.IsLocalHost();
                    activePlayers = GameNetworkAPI.GetNumActivePlayers();
                    var players = GameNetworkAPI.GetPlayers();
                    if (players != null)
                    {
                        otherHumanPlayers = 0;
                        foreach (var player in players)
                        {
                            // The game's own definition of "another real
                            // participant", used in every one of its own
                            // roster checks (Platform_Multiplayer send/kick/
                            // timeout paths): !isSelf && steamID > 1000 &&
                            // !skirmishAI. skirmishAI ALONE is not sufficient:
                            // the locally-created skirmish rosters
                            // (createLoadedSkirmishMembers, and the live
                            // skirmish roster measured on 2026-08-29 as
                            // active_humans=4) never set it, so counting
                            // !skirmishAI counted every AI lord as a human and
                            // suppressed the feature in ordinary solo play.
                            // Real Steam humans carry their 64-bit SteamID;
                            // AI and placeholder members carry 0.
                            if (player != null
                                && !player.kicked
                                && !player.skirmishAI
                                && !player.isSelf
                                && player.steamID > 1000UL)
                            {
                                otherHumanPlayers++;
                            }
                        }
                    }
                }
            }
            catch (Exception exception)
            {
                lock (_gate)
                {
                    // Die sichere Lage ist damit bereits hergestellt: bei
                    // unterdrueckter Miliz laeuft nichts, was in einer
                    // Mehrspielerpartie schaden koennte. Ein zusaetzliches
                    // FailDeferred wuerde daraus einen dauerhaften Ausfall
                    // machen und der naechsten Karte die Erholung nehmen -
                    // obwohl die Mitspielererkennung durchaus voruebergehend
                    // scheitern kann, wenn die Plattform-API beim Kartenstart
                    // noch nicht bereit ist.
                    _networkSuppressed = true;
                    _mapApplied = false;
                }
                _error(
                    "Worker militia could not determine the session roster at "
                    + "map start and suppressed itself for this map: "
                    + exception.GetType().Name + ": " + exception.Message
                    + ". The next map re-runs the detection.");
                return;
            }
            lock (_gate)
            {
                try
                {
                    // Close the operational gate before changing map-owned
                    // state. Crusader DE routes a locally-created skirmish
                    // through its network layer too, so only a non-host or a
                    // roster with another human is suppressed. Publish the
                    // already-sampled scope before _mapApplied is reopened at
                    // the very end of this branch.
                    _mapApplied = false;
                    _networkSuppressed =
                        !RuntimeSessionScopeDecision.AllowsLocalMutation(
                            networked,
                            localHost,
                            otherHumanPlayers);
                    _pendingWorkResumptionProofs.Clear();
                    _ownedProjectiles.Clear();
                    TryLiftSelectionQuarantineLocked();
                    if (_nativeSelectionDisabledForProcess
                        || (_pendingSelectionWorkerId > 0
                            && _selectionLease != null))
                    {
                        if (_pendingSelectionWorkerId > 0)
                        {
                            RequestOutstandingSelectionCancellation(
                                "map transition while native selection was pending",
                                true,
                                true);
                        }
                        int quarantinedWorkerId =
                            _pendingSelectionWorkerId > 0
                                ? _pendingSelectionWorkerId
                                : 0;
                        _inputPackets.Clear();
                        _pendingRightClickGesture = null;
                        _selectedWorkerId = 0;
                        _selectionQuarantineSuppressed = true;
                        ReturnAllOtherCommandsToWork(
                            quarantinedWorkerId,
                            "disabled map transition",
                            false);
                        if (quarantinedWorkerId == 0)
                        {
                            RequestSelectionReleaseAtNativeBoundary(
                                "disabled map transition");
                        }
                        RollbackWoodcutterRow("disabled map transition");
                        RollbackHunterHutAvailability(
                            "disabled map transition");
                        // Selection can remain quarantined without disabling
                        // the independent, previously-supported hut unlock.
                        ApplyHunterHutAvailability();
                        _warning(
                            "Worker militia remains quarantined on this map "
                            + "while an unresolved native selection settles. "
                            + "Its native observer remains active and will "
                            + "re-arm the local feature after a clean window.");
                        _mapApplied = true;
                        return;
                    }
                    ReturnAllToWork("map transition", false);
                    _selectionQuarantineSuppressed = false;
                    RequestSelectionReleaseAtNativeBoundary("map transition");
                    RollbackWoodcutterRow("map transition");
                    RollbackHunterHutAvailability("map transition");
                    // The user-facing hunter-hut unlock predates the militia
                    // controller and intentionally remains available in
                    // network maps. Only selection, commands and combat are
                    // suppressed there.
                    ApplyHunterHutAvailability();
                    _selectedWorkerId = 0;
                    _pendingSelectionWorkerId = 0;
                    _inputPackets.Clear();
                    _pendingRightClickGesture = null;
                    _evidenceLogged.Clear();
                    _scanCensusLogged = false;
                    ResetMapMeasurementStateLocked();
                    _archerProjectileProbesLogged = 0;
                    _naturalHunterProjectileProbesLogged = 0;
                    _commandedHunterProjectileProbesLogged = 0;
                    _lastArcherProjectileTick = 0;
                    _lastNaturalHunterProjectileTick = 0;
                    _lastCommandedHunterProjectileTick = 0;
                    _scanDurationSampleCount = 0;
                    _performanceEvidenceLogged = 0;
                    _nextScanTick = SimulationNowMilliseconds();
                    _info(RuntimeLogContract.WorkerMilitiaSessionScope(
                        networked,
                        localHost,
                        activePlayers,
                        otherHumanPlayers));
                    if (_networkSuppressed)
                    {
                        _pendingSavedCommands = null;
                        _pendingSavedSelection = null;
                        _pendingSavedProjectiles = null;
                        _pendingSaveVersion = 0;
                        _info(RuntimeLogContract.WorkerMilitiaMultiplayerSuppressed);
                        _warning(
                            "Worker militia combat and worker selection are disabled "
                            + "because another human is present or the network "
                            + "roster is indeterminate; this prevents "
                            + "desynchronisation.");
                        _mapApplied = true;
                        return;
                    }
                    ApplyWoodcutterRow();
                    RestorePendingSaveData();
                    _mapApplied = true;
                    string hunterStatus = GeneratedWorkerMilitiaContract
                            .HunterRangeCalibrated
                        ? "hunters use the reviewed native range calibration"
                        : "hunter combat is observation-only until native range "
                            + "evidence is reviewed";
                    _info(
                        "Worker militia armed: " + hunterStatus
                        + "; woodcutters guard within "
                        + GeneratedWorkerMilitiaContract.WoodcutterGuardRadius.ToString(
                            CultureInfo.InvariantCulture)
                        + " tiles with native melee damage. A commanded ground "
                        + "position is guarded for exactly "
                        + GeneratedWorkerMilitiaContract.HoldDurationMilliseconds
                            .ToString(CultureInfo.InvariantCulture)
                        + " simulation milliseconds, excluding combat.");
                }
                catch (Exception exception)
                {
                    FailDeferred("map-start apply", exception);
                }
            }
        }

        private void OnUnloadMap(MapUnloadEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            lock (_gate)
            {
                try
                {
                    _pendingWorkResumptionProofs.Clear();
                    _ownedProjectiles.Clear();
                    _lastConfirmedSelectionTribeId = 0;
                    _lastConfirmedSelectionUnitId = 0;
                    if (_pendingSelectionWorkerId > 0
                        && _selectionLease != null)
                    {
                        RequestOutstandingSelectionCancellation(
                            "map unload while native selection was pending",
                            true,
                            true);
                        _inputPackets.Clear();
                        _pendingRightClickGesture = null;
                        _selectedWorkerId = 0;
                        _scanCensusLogged = false;
                        _mapApplied = false;
                        _selectionQuarantineSuppressed = true;
                        ReturnAllOtherCommandsToWork(
                            _pendingSelectionWorkerId,
                            "pending map unload",
                            false);
                        RollbackWoodcutterRow("map unload");
                        RollbackHunterHutAvailability("map unload");
                        return;
                    }
                    ReturnAllToWork("map unload", false);
                    RequestSelectionReleaseAtNativeBoundary("map unload");
                    RollbackWoodcutterRow("map unload");
                    RollbackHunterHutAvailability("map unload");
                    _selectedWorkerId = 0;
                    _pendingSelectionWorkerId = 0;
                    _inputPackets.Clear();
                    _pendingRightClickGesture = null;
                    _scanCensusLogged = false;
                    _mapApplied = false;
                    _networkSuppressed = false;
                    _selectionQuarantineSuppressed = false;
                }
                catch (Exception exception)
                {
                    FailDeferred("map-unload rollback", exception);
                }
            }
        }

        private void OnProjectileDamage(UnitTakeDamageByProjectileExEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            lock (_gate)
            {
                if (!IsOperationalLocked())
                {
                    return;
                }
                int originalDamage = e.Damage;
                OwnedProjectile owned;
                if (!_ownedProjectiles.TryGetValue(e.ProjectileId, out owned))
                {
                    return;
                }
                // A native projectile damages at most once. Remove ownership
                // before validation so an exception or duplicate callback can
                // never apply the weak hit twice.
                _ownedProjectiles.Remove(e.ProjectileId);
                try
                {
                    GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                    // Ein Pfeil trifft, was im Weg steht - nicht zwingend die
                    // Einheit, auf die gezielt wurde. Bis zum 30.08.2026
                    // verlangte diese Pruefung genau das, samt globaler
                    // Kennung. Im Spiellauf desselben Tages wurden dadurch
                    // 238 von 238 eigenen Jaegerpfeilen auf e.Damage = 0
                    // gesetzt: in einem Gefecht mit vielen Gegnern trifft ein
                    // Pfeil fast nie den anvisierten. Der Jaeger richtete
                    // damit GAR NICHTS aus - schlechter als ohne den Mod.
                    //
                    // Was wirklich gesichert sein muss, ist die Herkunft, nicht
                    // das Ziel: das Geschoss gehoert uns (ProjectileId steht
                    // schon in _ownedProjectiles), es kam von UNSEREM Arbeiter,
                    // und es trifft einen GEGNER. Wen genau, entscheidet die
                    // Engine - wie bei jedem echten Bogenschuetzen auch.
                    bool sourceEventMatches = e.AttackingUnitId
                        == owned.WorkerUnitId;
                    bool victimIsLiveEnemy = IsPlausibleUnitId(e.AttackedUnitId)
                        && units.IsValid(e.AttackedUnitId)
                        && IsEnemyPlayerUnit(
                            owned.WorkerOwner,
                            units.GetOwner(e.AttackedUnitId));
                    if (!sourceEventMatches || !victimIsLiveEnemy)
                    {
                        e.Damage = 0;
                        if (_evidenceLogged.Add("arrow_suppressed"))
                        {
                            _warning(
                                "Worker militia suppressed an owned hunter "
                                + "arrow: it did not come from its own worker "
                                + "or did not hit an enemy. projectile_id="
                                + e.ProjectileId.ToString(
                                    CultureInfo.InvariantCulture)
                                + " source_matches="
                                + TelemetryBoolean(sourceEventMatches)
                                + " victim_is_enemy="
                                + TelemetryBoolean(victimIsLiveEnemy) + ".");
                        }
                        return;
                    }
                    if (e.AttackedUnitId != owned.TargetUnitId
                        && _evidenceLogged.Add("arrow_hit_other_enemy"))
                    {
                        _info(
                            "Worker militia hunter arrow hit a different enemy "
                            + "than the one it was aimed at; the weakened "
                            + "damage still applies, exactly as a vanilla "
                            + "archer's arrow would.");
                    }
                    e.Damage = owned.ReferenceDamage <= 0
                        ? 0
                        : Math.Max(
                            1,
                            owned.ReferenceDamage
                                / GeneratedWorkerMilitiaContract.DamageDivisor);
                    CommandState command = null;
                    if (e.Damage > 0
                        && _commands.TryGetValue(
                            owned.WorkerUnitId,
                            out command)
                        && command.WorkerGlobalId == owned.WorkerGlobalId
                        && command.Generation == owned.MilitiaGeneration)
                    {
                        command.DamageObserved = true;
                    }
                    string mode = command != null && command.Manual
                        ? "manual"
                        : "autonomous";
                    if (e.Damage > 0
                        && _evidenceLogged.Add("hunter_damage." + mode))
                    {
                        _info(RuntimeLogContract.WorkerMilitiaHunterDamageEvidence(
                            mode,
                            owned.ReferenceDamage,
                            e.Damage));
                        _info(
                            "Worker militia hunter arrow proof: intercepted="
                            + originalDamage.ToString(CultureInfo.InvariantCulture)
                            + " archer=" + owned.ReferenceDamage.ToString(
                                CultureInfo.InvariantCulture)
                            + " weak=" + e.Damage.ToString(
                                CultureInfo.InvariantCulture) + ".");
                    }
                }
                catch (Exception exception)
                {
                    // Once ProjectileId proves ownership, full damage is never
                    // a safe fallback. Contain the failure to this hit.
                    e.Damage = 0;
                    _warning(
                        "Worker militia suppressed an owned hunter arrow after "
                        + "a harmless damage-interception failure: projectile_id="
                        + e.ProjectileId.ToString(CultureInfo.InvariantCulture)
                        + " error=" + exception.GetType().Name + ".");
                }
            }
        }

        private void OnMeleeDamage(UnitTakeDamageByMeleeEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Post)
            {
                return;
            }
            lock (_gate)
            {
                if (!IsOperationalLocked())
                {
                    return;
                }
                try
                {
                    CommandState command;
                    if (!_commands.TryGetValue(e.AttackingUnitId, out command)
                        || command.WorkerType != eChimps.CHIMP_TYPE_WOODCUTTER
                        || !CommandMatchesLiveWorkerProvenance(
                            command,
                            e.AttackingUnitId)
                        || e.Damage <= 0)
                    {
                        return;
                    }
                    command.DamageObserved = true;
                    string mode = command.Manual ? "manual" : "autonomous";
                    if (_evidenceLogged.Add("woodcutter_damage." + mode))
                    {
                        _info(
                            RuntimeLogContract.WorkerMilitiaWoodcutterDamageEvidence(
                                mode,
                                e.Damage));
                    }
                }
                catch (Exception exception)
                {
                    _warning(
                        "Worker militia ignored a harmless woodcutter damage "
                        + "evidence failure: " + exception.GetType().Name + ".");
                }
            }
        }

        private void ProcessNativeInput()
        {
            while (_inputPackets.Count > 0)
            {
                InputPacket packet = _inputPackets.Dequeue();
                if (packet.RightDown)
                {
                    ProcessRightDown(packet);
                }
            }
        }

        private void CompleteNativeRun()
        {
            lock (_gate)
            {
                bool outstanding = _pendingSelectionWorkerId > 0
                    && _selectionLease != null;
                bool directWorkPending =
                    _pendingDirectWorkCompletions.Count > 0;
                bool boundarySelectionPending =
                    _boundarySelectionReleaseRequested;
                if (!WorkerMilitiaSafetyRules.ShouldObserveNativeRun(
                        _mapApplied,
                        _networkSuppressed,
                        _selectionQuarantineSuppressed,
                        outstanding,
                        directWorkPending,
                        boundarySelectionPending,
                        _commandClassRevertQueue.Pending
                            || CommandClassNeedsRevertLocked()
                            || HunterMoveStateNeedsRevertLocked(),
                        _deferredRollbackRequested))
                {
                    return;
                }
                _insideNativeRunPostfix = true;
                try
                {
                    int currentThreadId = Thread.CurrentThread.ManagedThreadId;
                    if (_nativeRunThreadId == 0)
                    {
                        _nativeRunThreadId = currentThreadId;
                    }
                    if (currentThreadId != _nativeRunThreadId
                        || (_mainThreadId > 0
                            && currentThreadId == _mainThreadId))
                    {
                        // Das ist eine echte Sicherheitsinvariante - unsere
                        // Speichereingriffe haengen an diesem Faden. Aber ein
                        // Wurf hier wandert durch nativen Engine-Code zurueck.
                        // Der Ausfall wird deshalb vermerkt und beim naechsten
                        // Tick an sicherer Stelle gemeldet.
                        FailDeferred(
                            "native-run postfix thread identity",
                            new InvalidOperationException(
                                "EngineInterface.run postfix changed thread "
                                + "identity"));
                        return;
                    }
                    CompletePendingDirectWorkAtNativeBoundary();
                    CompleteBoundarySelectionReleaseAtNativeBoundary();
                    if (_deferredRollbackRequested
                        && _pendingSelectionWorkerId <= 0
                        && _pendingDirectWorkCompletions.Count == 0
                        && _commands.Count == 0
                        && _selectionLease == null
                        && !_boundarySelectionReleaseRequested
                        && !_commandClassRevertQueue.Pending
                        && !CommandClassNeedsRevertLocked())
                    {
                        TryRevertHunterMoveStateAtNativeBoundaryLocked(
                            "settled feature rollback");
                    }
                    MarkDeferredRollbackReadyAtNativeBoundary();
                    if (_nativeSelectionPacketInFlight
                        && _directSelectionMouseUpAccepted)
                    {
                        // The same owned singleton is refreshed on hold/up
                        // whenever EditorDirector's small-drag action replaces
                        // its arrays. Only the run which consumed an accepted
                        // mouse-up may clear all three managed replay sources
                        // coherently.
                        ClearInjectedNativeSelectionCandidate(
                            EditorDirector.instance);
                        _nativeSelectionPacketInFlight = false;
                    }
                    if (_nativeSelectionLifecycle
                        == NativeSelectionLifecycle.PacketInjected)
                    {
                        // The one and only down packet has passed through
                        // DLL_TroopSelection. Its queued native chore may be
                        // observed on this or a later DLL_RunTick.
                        _nativeSelectionLifecycle =
                            NativeSelectionLifecycle.AwaitingCommit;
                    }
                    int pending = _pendingSelectionWorkerId;
                    int[] selected = GetPinnedNativeSelectedIds();
                    if (pending > 0)
                    {
                        NativeSelectionLease pendingLease = _selectionLease;
                        bool pendingInOutput = Array.IndexOf(
                            selected,
                            pending) >= 0;
                        if (pendingInOutput)
                        {
                            bool identityMatches = false;
                            if (pendingLease != null
                                && GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                                    pending,
                                    out var pendingPointer))
                            {
                                ref GameUnit pendingUnit =
                                    ref pendingPointer.AsRef();
                                // Identitaet, nicht Beschaeftigung. Die Folge
                                // hier ist das dauerhafte Abschalten der
                                // nativen Auswahl; ein verlorener Arbeitsplatz
                                // darf das niemals ausloesen.
                                identityMatches = SelectionLeaseIdentityMatches(
                                    pendingLease,
                                    ref pendingUnit);
                            }
                            if (!identityMatches)
                            {
                                _pendingSelectionCancellationRequested = true;
                                _pendingSelectionIdentityInvalidated = true;
                                _nativeSelectionDisabledForProcess = true;
                                if (!_nativeCommandClassUnavailableForProcess)
                                {
                                    _selectionQuarantineSuppressed = true;
                                }
                                _pendingSelectionCancellationReason =
                                    "late native commit changed unit identity";
                                _nativeSelectionLifecycle =
                                    NativeSelectionLifecycle.Quarantined;
                            }
                            if (selected.Length != 1
                                && !_pendingSelectionIdentityInvalidated)
                            {
                                _pendingSelectionCancellationRequested = true;
                                _pendingSelectionCancellationReason =
                                    "late native worker commit joined another selection";
                                if (!_pendingSelectionIdentityInvalidated)
                                {
                                    _nativeSelectionLifecycle =
                                        NativeSelectionLifecycle.CancelAwaitingCommit;
                                }
                            }
                            if (!_directSelectionMouseUpAccepted
                                && !_pendingSelectionCancellationRequested
                                && HasReached(
                                    SimulationNowMilliseconds(),
                                    _directSelectionDeadlineTick))
                            {
                                RequestOutstandingSelectionCancellation(
                                    "native selection mouse-up/confirmation timeout",
                                    false,
                                    false);
                                _nativeSelectionLifecycle =
                                    NativeSelectionLifecycle.Quarantined;
                            }
                            if (_pendingSelectionCancellationRequested)
                            {
                                string cancellationReason =
                                    _pendingSelectionCancellationReason
                                    ?? "cancelled late native selection";
                                if (_pendingSelectionIdentityInvalidated)
                                {
                                    string quarantineKey =
                                        "native_selection_identity_quarantine."
                                        + pending.ToString(
                                            CultureInfo.InvariantCulture);
                                    if (_evidenceLogged.Add(quarantineKey))
                                    {
                                        _error(
                                            "Worker militia observed a late "
                                            + "selection for a changed/cross-map "
                                            + "unit slot; it did not clear or "
                                            + "restore that foreign identity. "
                                            + "The observer remains installed "
                                            + "for process quarantine: unit_id="
                                            + pending.ToString(
                                                CultureInfo.InvariantCulture)
                                            + ".");
                                    }
                                    return;
                                }
                                ClearPinnedNativeSelectionUnit(
                                    pending,
                                    GamePlayerManagerAPI.Instance
                                        .GetLocalPlayerId(),
                                    cancellationReason);
                                FinalizePendingNativeSelection(
                                    cancellationReason);
                                return;
                            }
                            if (_directSelectionMouseUpAccepted
                                && selected.Length == 1
                                && identityMatches)
                            {
                                ConfirmNativeSelection(
                                    pending,
                                    "one-shot DLL_TroopSelection chore and "
                                    + "DLL_RunTick output after mouse-up");
                            }
                            return;
                        }
                        if (_pendingSelectionIdentityInvalidated
                            && TryFinalizeInvalidatedPendingSelectionLocked(
                                selected))
                        {
                            return;
                        }
                        if (!_pendingSelectionCancellationRequested
                            && HasReached(
                                SimulationNowMilliseconds(),
                                _directSelectionDeadlineTick))
                        {
                            eChimps type = GameUnitManagerAPI.Instance.IsValid(pending)
                                ? GameUnitManagerAPI.Instance.GetType(pending)
                                : eChimps.CHIMP_TYPE_WOODCUTTER;
                            _warning(
                                "Worker militia native DLL_TroopSelection chore "
                                + "was not confirmed before timeout for "
                                + UnitName(type) + "; the unstornierable request "
                                + "remains quarantined and observed.");
                            RequestOutstandingSelectionCancellation(
                                "native selection confirmation timeout",
                                false,
                                false);
                            _nativeSelectionLifecycle =
                                NativeSelectionLifecycle.Quarantined;
                        }
                        return;
                    }

                    TryLiftSelectionQuarantineInMapLocked(selected);

                    int selectedMilitia = selected != null
                        && selected.Length == 1
                        && IsLocalMilitia(selected[0])
                            ? selected[0]
                            : 0;
                    if (selectedMilitia > 0)
                    {
                        if (_selectionLease == null)
                        {
                            string staleSelectionKey =
                                "stale_native_selection."
                                + selectedMilitia.ToString(
                                    CultureInfo.InvariantCulture);
                            _selectedWorkerId = 0;
                            FilterWorkerFromNativeSelectionPacket(
                                EditorDirector.instance,
                                selectedMilitia);
                            ClearPinnedNativeSelectionUnit(
                                selectedMilitia,
                                GamePlayerManagerAPI.Instance.GetLocalPlayerId(),
                                "unowned stale worker singleton");
                            if (_evidenceLogged.Add(staleSelectionKey))
                            {
                                _warning(
                                    "Worker militia cleared an unowned stale "
                                    + "native worker singleton exactly: unit_id="
                                    + selectedMilitia.ToString(
                                        CultureInfo.InvariantCulture) + ".");
                            }
                            return;
                        }
                        if (_selectionLease.UnitId != selectedMilitia)
                        {
                            _warning(
                                "Worker militia observed a native worker selection "
                                + "owned by a different lease; it was not adopted.");
                            _selectedWorkerId = 0;
                            return;
                        }
                        return;
                    }

                    _selectedWorkerId = 0;
                    LogNativeDeselectionDuringRightClick(selected);
                    ReleaseNativeSelection(NativeDeselectionReleaseReason);
                }
                catch (Exception exception)
                {
                    ContainOrdinaryEventFailure(
                        "post-DLL_RunTick selection completion",
                        exception,
                        true);
                }
                finally
                {
                    // A right-click is promoted only after this native run has
                    // consumed its matching mouse-up and fired any synchronous
                    // UnitMoveHere Post callback. It can never reach Tick from
                    // the earlier mouse-down frame.
                    try
                    {
                        PromoteReleasedRightClickGestureAfterNativeRun();
                    }
                    finally
                    {
                        _insideNativeRunPostfix = false;
                    }
                }
            }
        }

        private void FinalizePendingNativeSelection(string reason)
        {
            NativeSelectionLease lease = _selectionLease;
            if (_pendingSelectionIdentityInvalidated || lease == null)
            {
                // No lease means there is no owned release to perform - but the
                // pending bookkeeping must still be cleared. Throwing here left
                // _pendingSelectionWorkerId set, which makes every later
                // selection refuse ("a different worker cannot take ownership
                // while a chore is pending"), while the only path that would
                // have cleared it - the selection timeout - runs straight back
                // into this method. That is a closed loop: no worker can ever
                // be selected again on that map.
                //
                // Nothing foreign is touched: only this feature's own fields
                // are reset. A changed identity is deliberately left alone,
                // exactly as before.
                if (_evidenceLogged.Add("finalize_without_lease"))
                {
                    _warning(
                        "Worker militia finalised a pending native selection "
                        + "without a lease (" + reason
                        + ", identity_invalidated="
                        + TelemetryBoolean(_pendingSelectionIdentityInvalidated)
                        + "). Its own pending state is cleared so selection "
                        + "keeps working; no foreign unit was touched.");
                }
                if (lease != null)
                {
                    EndCommandClassLease(lease, reason);
                }
                else if (_commandClassLeaseGeneration != 0)
                {
                    _nativeSelectionDisabledForProcess = true;
                    if (!_nativeCommandClassUnavailableForProcess)
                    {
                        _selectionQuarantineSuppressed = true;
                    }
                    RequestCommandClassRevertLocked(
                        "orphaned patch while finalising selection: " + reason);
                }
                _pendingSelectionWorkerId = 0;
                _selectionLease = null;
                _nativeSelectionPacketInFlight = false;
                _directClickGestureUnitId = 0;
                _confirmedSelectionGestureNoOp = false;
                _directSelectionMouseUpAccepted = false;
                _pendingRightClickGesture = null;
                _pendingSelectionCancellationRequested = false;
                _pendingSelectionIdentityInvalidated = false;
                _pendingSelectionCancellationReason = null;
                _directSelectionDeadlineTick = 0;
                _selectedWorkerId = 0;
                _nativeSelectionLifecycle =
                    _nativeSelectionDisabledForProcess
                        ? NativeSelectionLifecycle.Quarantined
                        : NativeSelectionLifecycle.Idle;
                return;
            }
            _pendingSelectionWorkerId = 0;
            _nativeSelectionPacketInFlight = false;
            _directClickGestureUnitId = 0;
            _confirmedSelectionGestureNoOp = false;
            _directSelectionMouseUpAccepted = false;
            _pendingRightClickGesture = null;
            _pendingSelectionCancellationRequested = false;
            _pendingSelectionCancellationReason = null;
            _directSelectionDeadlineTick = 0;
            _selectedWorkerId = 0;
            ReleaseNativeSelection(reason);
            if (_deferredRollbackRequested)
            {
                ReturnAllToWork("settled deferred feature rollback", false);
                RequestSelectionReleaseAtNativeBoundary(
                    "settled deferred feature rollback");
                CompletePendingDirectWorkAtNativeBoundary();
                CompleteBoundarySelectionReleaseAtNativeBoundary();
                MarkDeferredRollbackReadyAtNativeBoundary();
            }
        }

        private bool TryFinalizeInvalidatedPendingSelectionLocked(int[] selected)
        {
            int selectedCount = GetPinnedNativeSelectedCount();
            bool cleanAuthoritativeOutput = selectedCount == 0
                && selected != null
                && selected.Length == 0
                && !_nativeSelectionPacketInFlight;
            if (!cleanAuthoritativeOutput)
            {
                _quarantineCleanSinceTick = 0;
                _quarantineCleanRunCount = 0;
                return false;
            }
            int now = SimulationNowMilliseconds();
            if (_quarantineCleanRunCount == 0)
            {
                _quarantineCleanSinceTick = now;
            }
            _quarantineCleanRunCount++;
            if (_quarantineCleanRunCount < SelectionQuarantineCleanRunFloor
                || !HasReached(
                    now,
                    unchecked(
                        _quarantineCleanSinceTick
                        + SelectionQuarantineGraceMilliseconds)))
            {
                return false;
            }
            _quarantineCleanSinceTick = 0;
            _quarantineCleanRunCount = 0;
            FinalizePendingNativeSelection(
                "invalidated late selection stayed absent through the stable "
                + "same-map observation window");
            return true;
        }

        private void RequestSelectionReleaseAtNativeBoundary(string reason)
        {
            if (_selectionLease == null)
            {
                return;
            }
            _selectedWorkerId = 0;
            _boundarySelectionReleaseRequested = true;
            _boundarySelectionReleaseReason = reason;
        }

        private void CompleteBoundarySelectionReleaseAtNativeBoundary()
        {
            if (!_boundarySelectionReleaseRequested
                || _pendingSelectionWorkerId > 0)
            {
                return;
            }
            if (!_insideNativeRunPostfix
                || Thread.CurrentThread.ManagedThreadId != _nativeRunThreadId)
            {
                if (_evidenceLogged.Add("selection_release_boundary_escaped"))
                {
                    _warning(
                        "Worker militia selection release was reached outside "
                        + "the native run postfix; it stays queued for the "
                        + "next boundary.");
                }
                return;
            }
            string reason = _boundarySelectionReleaseReason
                ?? "queued native-boundary selection release";
            if (_selectionLease != null)
            {
                _selectedWorkerId = 0;
                DeselectOwnedMilitia(reason);
                ReleaseNativeSelection(reason, false);
            }
            _boundarySelectionReleaseRequested = false;
            _boundarySelectionReleaseReason = null;
        }

        private void MarkDeferredRollbackReadyAtNativeBoundary()
        {
            if (!_deferredRollbackRequested
                || _pendingSelectionWorkerId > 0
                || _pendingDirectWorkCompletions.Count > 0
                || _commands.Count > 0
                || _selectionLease != null
                || _boundarySelectionReleaseRequested
                || _commandClassRevertQueue.Pending
                || CommandClassNeedsRevertLocked()
                || HunterMoveStateNeedsRevertLocked())
            {
                return;
            }
            _deferredRollbackReady = true;
            QueueDeferredRollbackAtSafeBoundary();
        }

        private void QueueDeferredRollbackAtSafeBoundary()
        {
            if (!_deferredRollbackRequested
                || !_deferredRollbackReady
                || _deferredRollbackQueued)
            {
                return;
            }
            SynchronizationContext context = _mainThreadContext;
            if (context == null)
            {
                _error(
                    "Worker militia could not queue its settled deferred "
                    + "rollback because the Unity main-thread context was "
                    + "unavailable; native observers remain fail-closed.");
                return;
            }
            _deferredRollbackQueued = true;
            context.Post(
                state =>
                {
                    try
                    {
                        CompleteDeferredRollbackAtSafeBoundary();
                    }
                    catch (Exception exception)
                    {
                        lock (_gate)
                        {
                            _deferredRollbackQueued = false;
                        }
                        _error(
                            "Worker militia settled deferred rollback failed: "
                            + exception);
                    }
                },
                null);
        }

        private void CompleteDeferredRollbackAtSafeBoundary()
        {
            lock (_gate)
            {
                _deferredRollbackQueued = false;
                if (!_deferredRollbackRequested
                    || !_deferredRollbackReady
                    || _pendingSelectionWorkerId > 0
                    || _pendingDirectWorkCompletions.Count > 0
                    || _commands.Count > 0
                    || _selectionLease != null
                    || _boundarySelectionReleaseRequested
                    || _commandClassRevertQueue.Pending
                    || CommandClassNeedsRevertLocked()
                    || HunterMoveStateNeedsRevertLocked())
                {
                    return;
                }
            }
            // This runs from MonoBehaviour.Update or a posted Unity main-loop
            // continuation, never re-entrantly inside EngineInterface.run's
            // Harmony postfix which observed the native settlement.
            RollbackOwned();
        }

        /// <summary>
        /// Gives up one unconfirmable selection without giving up the feature.
        /// </summary>
        private void DeclineNativeSelection(
            string reason,
            int unitId,
            string nativePath)
        {
            _warning(
                "Worker militia could not confirm a native selection and "
                + "cancelled it: reason=" + reason
                + " unit_id=" + unitId.ToString(CultureInfo.InvariantCulture)
                + " path=" + nativePath
                + ". The click is lost, the feature keeps running; click again.");
            RequestOutstandingSelectionCancellation(
                "unconfirmable native selection (" + reason + ")",
                false,
                false);
        }

        private void ConfirmNativeSelection(int selectedMilitia, string nativePath)
        {
            NativeSelectionLease lease = _selectionLease;
            // None of the three refusals below is a broken contract. They all
            // say "this one click cannot be confirmed" - and a click that
            // cannot be confirmed must cost the click, not the feature. Until
            // 2026-08-27 each of them threw on the run-postfix path, where the
            // deferred failure stops the militia for the rest of the session.
            // The selection is cancelled through the same proven path the
            // caller already uses for its other refusals, without quarantine,
            // so the player can simply click again.
            if (lease == null
                || lease.UnitId != selectedMilitia
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    selectedMilitia,
                    out var pointer))
            {
                DeclineNativeSelection(
                    "no matching owned lease",
                    selectedMilitia,
                    nativePath);
                return;
            }
            ref GameUnit selectedUnit = ref pointer.AsRef();
            if (!SelectionLeaseMatches(lease, ref selectedUnit)
                || SeInteropFieldAliases.CommandMode(ref selectedUnit) != 1
                || selectedUnit.r_UnitHover != 1
                || selectedUnit.r_UnitSelected != lease.Owner)
            {
                DeclineNativeSelection(
                    "command-selection fields were lost between commit and "
                    + "confirmation",
                    selectedMilitia,
                    nativePath);
                return;
            }
            int liveWorkLink = ReadExposedUnitInt(
                selectedMilitia,
                "r_LinkedProductionBuildingId");
            int liveTribeId;
            bool tribeMatches = TribeProvenanceMatches(
                selectedMilitia,
                lease.OriginalTribeId,
                out liveTribeId);
            if (liveWorkLink != lease.OriginalWorkLink || !tribeMatches)
            {
                // Name both observed values: the bare message hid for a full
                // day that it was always the tribe (the native commit groups
                // every selected unit, see TribeProvenanceMatches), never the
                // work link.
                DeclineNativeSelection(
                    "work/tribe provenance changed: work_link="
                    + liveWorkLink.ToString(CultureInfo.InvariantCulture)
                    + " expected_work_link="
                    + lease.OriginalWorkLink.ToString(CultureInfo.InvariantCulture)
                    + " tribe="
                    + liveTribeId.ToString(CultureInfo.InvariantCulture)
                    + " pre_selection_tribe="
                    + lease.OriginalTribeId.ToString(CultureInfo.InvariantCulture)
                    + " selection_owner="
                    + selectedUnit.r_UnitSelected.ToString(
                        CultureInfo.InvariantCulture),
                    selectedMilitia,
                    nativePath);
                return;
            }
            _directSelectionDeadlineTick = 0;
            _nativeSelectionPacketInFlight = false;
            _directClickGestureUnitId = 0;
            _confirmedSelectionGestureNoOp = false;
            _directSelectionMouseUpAccepted = false;
            _pendingRightClickGesture = null;
            _pendingSelectionCancellationRequested = false;
            _pendingSelectionIdentityInvalidated = false;
            _pendingSelectionCancellationReason = null;
            _pendingSelectionWorkerId = 0;
            _selectedWorkerId = selectedMilitia;
            _nativeSelectionLifecycle = NativeSelectionLifecycle.Confirmed;
            _lastConfirmedSelectionTribeId = liveTribeId;
            _lastConfirmedSelectionUnitId = selectedMilitia;
            eChimps selectedType =
                GameUnitManagerAPI.Instance.GetType(selectedMilitia);
            string unit = UnitName(selectedType);
            if (_evidenceLogged.Add("selected." + unit))
            {
                _info(RuntimeLogContract.WorkerMilitiaSelectionEvidence(unit));
            }
            _info(
                "Worker militia native selection confirmed after "
                + nativePath + ": unit=" + unit + " unit_id="
                + selectedMilitia.ToString(
                    CultureInfo.InvariantCulture)
                + " command_mode=1 selection_owner="
                + lease.Owner.ToString(CultureInfo.InvariantCulture)
                + " selection_tribe="
                + liveTribeId.ToString(CultureInfo.InvariantCulture)
                + " pre_selection_tribe="
                + lease.OriginalTribeId.ToString(CultureInfo.InvariantCulture)
                + ".");
        }

        private void ProcessRightDown(InputPacket packet)
        {
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            int workerId = packet.SelectedWorkerId;
            UnitSnapshot worker = CaptureUnit(workerId);
            if (worker == null
                || worker.GlobalId != packet.SelectedWorkerGlobalId
                || worker.Owner != packet.SelectedWorkerOwner
                || worker.Type != packet.SelectedWorkerType
                || worker.Owner != players.GetLocalPlayerId()
                || !IsMilitia(worker.Type))
            {
                return;
            }
            eChimps workerType = worker.Type;
            if (packet.HoveredUnitId > 0)
            {
                UnitSnapshot target = CaptureUnit(packet.HoveredUnitId);
                if (target == null
                    || target.GlobalId != packet.HoveredUnitGlobalId
                    || target.Owner != packet.HoveredUnitOwner
                    || target.Type != packet.HoveredUnitType)
                {
                    // The down event selected this exact native unit slot.
                    // Never retarget a later occupant (or reinterpret the
                    // stale enemy click as a ground order) after mouse-up.
                    return;
                }
                if (!IsEnemyPlayerUnit(worker.Owner, target.Owner))
                {
                    // A live friendly/neutral unit under the down position is
                    // not a militia attack target. Preserve the native input
                    // result and do not manufacture a fallback order.
                    return;
                }
                bool started = StartOrRetarget(
                    workerId,
                    workerType,
                    packet.HoveredUnitId,
                    true,
                    SimulationNowMilliseconds());
                string unit = UnitName(workerType);
                if (started)
                {
                    RaiseNativeCommandMarker(workerId, "attack");
                    if (_evidenceLogged.Add("command." + unit + ".manual"))
                    {
                        _info(RuntimeLogContract.WorkerMilitiaCommandEvidence(
                            unit,
                            "manual"));
                    }
                }
                return;
            }
            if (!packet.HasGroundDestination)
            {
                return;
            }
            int now = SimulationNowMilliseconds();
            if (packet.NativeMoveObserved && packet.NativeMoveAccepted)
            {
                // The callback can occur on the right-button-down native run,
                // before mouse-up marks the gesture Released. It was captured
                // on the packet and is committed here, on Tick, exactly once.
                // Never repeat an already accepted native path through the
                // fallback wrapper.
                if (AcceptManualDestination(
                        workerId,
                        packet.GroundDestinationX,
                        packet.GroundDestinationY,
                        false,
                        now,
                        "native OnUnitMoveHere"))
                {
                    RaiseNativeCommandMarker(workerId, "move");
                }
                return;
            }
            if (packet.NativeMoveSequenceAtCapture != _nativeMoveSequence
                && !packet.NativeMoveObserved)
            {
                // A different already-accounted native callback crossed this
                // stale packet. Identity-bound packets are never reinterpreted
                // as a new fallback order.
                return;
            }
            if (AcceptManualDestination(
                    workerId,
                    packet.GroundDestinationX,
                    packet.GroundDestinationY,
                    true,
                    now,
                    "right-click fallback"))
            {
                RaiseNativeCommandMarker(workerId, "move");
                _info(
                    "Worker militia native ground-order callback was absent; "
                    + "the preserved right-click destination was issued through "
                    + "the Extender's native MoveToTile entry point.");
            }
        }

        private void OnMoveHere(UnitMoveHereEventArgs e)
        {
            if (e == null)
            {
                return;
            }
            lock (_gate)
            {
                if (!IsOperationalLocked())
                {
                    return;
                }
                try
                {
                    if (e.Phase == EventHookPhase.Post
                        && _internalMoveDepth > 0)
                    {
                        if (e.UnitId == _internalMoveUnitId
                            && e.TileX == _internalMoveTileX
                            && e.TileY == _internalMoveTileY)
                        {
                            // GameUnitManagerAPI.MoveToTile discards the
                            // native long, but its synchronous Post event does
                            // not. Capture the actual 0/1 result before the
                            // void wrapper returns to MoveWorker.
                            _internalMovePostObserved = true;
                            _internalMoveReturnValue = e.ReturnValue;
                        }
                        return;
                    }
                    if (e.Phase == EventHookPhase.Pre)
                    {
                        CommandState command;
                        if (_internalMoveDepth > 0
                            || !_commands.TryGetValue(e.UnitId, out command))
                        {
                            return;
                        }
                        if (!CommandMatchesLiveWorkerProvenance(
                                command,
                                e.UnitId))
                        {
                            return;
                        }
                        if (MoveMatchesPendingRightClickGesture(
                                e,
                                false))
                        {
                            return;
                        }
                        e.SkipOriginalFunction = true;
                        e.ReturnValue = 0;
                        string suppressedUnit = UnitName(command.WorkerType);
                        string suppressedPhase = MissionPhaseName(command.Phase);
                        string suppressionKey = "native_work_move_suppressed."
                            + suppressedUnit + "." + suppressedPhase;
                        if (_evidenceLogged.Add(suppressionKey))
                        {
                            _info(
                                RuntimeLogContract
                                    .WorkerMilitiaNativeWorkMoveSuppressedEvidence(
                                        suppressedUnit,
                                        suppressedPhase));
                        }
                        return;
                    }
                    if (e.Phase != EventHookPhase.Post)
                    {
                        return;
                    }
                    bool matchesUserGesture =
                        MoveMatchesPendingRightClickGesture(e, false);
                    if (!matchesUserGesture)
                    {
                        CompleteWorkResumptionProofFromNativeMove(e.UnitId);
                        return;
                    }
                    bool matchesGroundGesture =
                        MoveMatchesPendingRightClickGesture(e, true);
                    if (!matchesGroundGesture)
                    {
                        // Enemy-target right-clicks use the same native move
                        // callback but are not worker-AI activity and cannot
                        // prove that a previous direct-work handoff resumed.
                        return;
                    }
                    RightClickGesture gesture = _pendingRightClickGesture;
                    InputPacket packet = gesture == null
                        ? null
                        : gesture.Packet;
                    if (packet == null)
                    {
                        return;
                    }
                    bool wasAccepted = packet.NativeMoveAccepted;
                    packet.NativeMoveObserved = true;
                    packet.NativeMoveReturnValue = e.ReturnValue;
                    if (e.ReturnValue > 0)
                    {
                        packet.NativeMoveAccepted = true;
                    }
                    if (!wasAccepted && packet.NativeMoveAccepted)
                    {
                        _nativeMoveSequence = unchecked(_nativeMoveSequence + 1);
                        string unit = SafeUnitName(e.UnitId);
                        if (_evidenceLogged.Add("native_move." + unit))
                        {
                            _info(
                                RuntimeLogContract
                                    .WorkerMilitiaNativeMoveEvidence(unit));
                        }
                    }
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = false;
                    ContainOrdinaryEventFailure(
                        "native move capture",
                        exception,
                        true);
                }
            }
        }

        private bool MoveMatchesPendingRightClickGesture(
            UnitMoveHereEventArgs e,
            bool requireGroundDestination)
        {
            RightClickGesture gesture = _pendingRightClickGesture;
            InputPacket packet = gesture == null ? null : gesture.Packet;
            NativeSelectionLease lease = _selectionLease;
            if (packet == null
                || lease == null
                || packet.SelectedWorkerId != e.UnitId
                || lease.UnitId != e.UnitId
                || lease.GlobalId != packet.SelectedWorkerGlobalId
                || lease.Owner != packet.SelectedWorkerOwner
                || lease.Type != packet.SelectedWorkerType
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    e.UnitId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (!SelectionLeaseMatches(lease, ref unit))
            {
                return false;
            }
            if (packet.HoveredUnitId > 0)
            {
                return !requireGroundDestination;
            }
            if (!packet.HasGroundDestination)
            {
                return false;
            }
            return packet.GroundDestinationX == e.TileX
                && packet.GroundDestinationY == e.TileY;
        }

        private bool AcceptManualDestination(
            int workerId,
            int tileX,
            int tileY,
            bool issueNativeMove,
            int now,
            string path)
        {
            if (!IsOperationalLocked() || !IsValidMapTile(tileX, tileY))
            {
                return false;
            }
            UnitSnapshot worker = CaptureUnit(workerId);
            if (worker == null
                || !IsMilitia(worker.Type)
                || !IsValidMapTile(worker.X, worker.Y))
            {
                return false;
            }
            CommandState command;
            bool createdCommand = false;
            if (!_commands.TryGetValue(workerId, out command))
            {
                command = CreateCommand(worker, true);
                if (command == null || !EnsureCommandMode(command, false))
                {
                    return false;
                }
                _pendingWorkResumptionProofs.Remove(workerId);
                _commands.Add(workerId, command);
                createdCommand = true;
            }
            else if (!EnsureCommandMode(command, false))
            {
                return false;
            }

            // Do not publish a destination before its path has actually been
            // accepted. MoveToTile is a void wrapper, but OnMoveHere Post
            // carries the native 0/1 return and MoveWorker captures it
            // synchronously. The native tribe path was already accepted and
            // only needs its 0x65 state/readback bound to this command.
            bool pathAccepted;
            if (issueNativeMove)
            {
                pathAccepted = MoveWorker(
                    command,
                    tileX,
                    tileY,
                    now,
                    "manual destination fallback");
            }
            else
            {
                pathAccepted = ApplyNativeMilitiaMoveState(
                    command,
                    "native ground order");
                if (pathAccepted)
                {
                    command.HasIssuedMove = true;
                    command.IssuedMoveX = ClampMapTile(tileX);
                    command.IssuedMoveY = ClampMapTile(tileY);
                    command.LastProgressTick = now;
                    command.NextMoveTick = unchecked(
                        now
                        + GeneratedWorkerMilitiaContract
                            .MoveRefreshMilliseconds);
                    ResetMovementStall(command, now);
                }
            }
            if (!pathAccepted)
            {
                if (createdCommand)
                {
                    CompleteDirectWork(
                        command,
                        worker,
                        "manual_destination_rejected",
                        false,
                        false);
                }
                return false;
            }

            command.Manual = true;
            command.ExplicitTarget = false;
            command.TargetUnitId = 0;
            command.TargetGlobalId = 0;
            command.Phase = MissionPhase.Outbound;
            command.HasManualDestination = true;
            command.ManualDestinationReached = false;
            command.ManualDestinationX = tileX;
            command.ManualDestinationY = tileY;
            command.HoldDeadlineTick = 0;
            command.ResumeHoldAfterCombat = false;
            command.PausedHoldRemainingMilliseconds = 0;
            command.OrderPath = path;
            command.CombatAnchorX = tileX;
            command.CombatAnchorY = tileY;
            command.LastProgressX = worker.X;
            command.LastProgressY = worker.Y;
            string unit = UnitName(worker.Type);
            if (_evidenceLogged.Add("command." + unit + ".manual"))
            {
                _info(RuntimeLogContract.WorkerMilitiaCommandEvidence(
                    unit,
                    "manual"));
            }
            _info(
                "Worker militia accepted movement destination via " + path
                + ": unit=" + unit + " tile="
                + command.ManualDestinationX.ToString(
                    CultureInfo.InvariantCulture) + ","
                + command.ManualDestinationY.ToString(
                    CultureInfo.InvariantCulture) + ".");
            return true;
        }

        /// <summary>
        /// Observes, but never vetoes, the native ground order for the
        /// worker's singleton selection tribe.
        /// </summary>
        /// <remarks>
        /// A right-click with the worker selected makes the native input
        /// handler (CrusaderDE.dll RVA 0x8E892 branch, mode 1) queue chore
        /// 0x11 through RVA 0x194B70. Its handler 0x10AE0 calls 0x194E40 and
        /// the tribe executor 0x11A3C0. That executor sets every accepted
        /// member to AI state 0x65 at 0x11AE2B before calling the real per-unit
        /// path writer 0x194FC0 at 0x11AEF7. The previous veto prevented both
        /// the state transition and OnUnitMoveHere itself, which exactly
        /// explains why every runtime trace reported right-click fallback and
        /// no native_move evidence. Target orders remain separately vetoed:
        /// worker combat is still owned by this feature's bounded adapter.
        /// </remarks>
        private void OnTribeMoveOrder(TribeIssueOrderMoveHereEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            lock (_gate)
            {
                if (!IsOperationalLocked())
                {
                    return;
                }
                try
                {
                    int unitId;
                    if (!TryGetOwnedSelectionTribeWorker(e.TribeId, out unitId))
                    {
                        LogFormerSelectionTribeOrder(
                            "move",
                            e.TribeId,
                            "tile=" + e.TileX.ToString(CultureInfo.InvariantCulture)
                            + "," + e.TileY.ToString(CultureInfo.InvariantCulture)
                            + " move_type=" + e.MoveType.ToString());
                        return;
                    }
                    string key = "native_tribe_move_allowed."
                        + SafeUnitName(unitId);
                    if (_evidenceLogged.Add(key))
                    {
                        _info(
                            "Worker militia allowed the engine's own tribe "
                            + "ground order: unit=" + SafeUnitName(unitId)
                            + " tribe="
                            + e.TribeId.ToString(CultureInfo.InvariantCulture)
                            + " tile="
                            + e.TileX.ToString(CultureInfo.InvariantCulture)
                            + ","
                            + e.TileY.ToString(CultureInfo.InvariantCulture)
                            + " move_type=" + e.MoveType.ToString()
                            + ". The native executor now owns state 0x65 and "
                            + "the first path attempt.");
                    }
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = false;
                    ContainOrdinaryEventFailure(
                        "native tribe move-order observation",
                        exception,
                        true);
                }
            }
        }

        private void OnTribeTargetOrder(TribeIssueOrderWithTargetEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            lock (_gate)
            {
                if (!IsOperationalLocked())
                {
                    return;
                }
                try
                {
                    int unitId;
                    if (!TryGetOwnedSelectionTribeWorker(e.TribeId, out unitId))
                    {
                        LogFormerSelectionTribeOrder(
                            "target",
                            e.TribeId,
                            "command=" + e.AICommand.ToString()
                            + " target1="
                            + e.TargetValue1.ToString(CultureInfo.InvariantCulture)
                            + " target2="
                            + e.TargetValue2.ToString(CultureInfo.InvariantCulture));
                        return;
                    }
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 0;
                    LogVetoedNativeTribeOrder(
                        "target",
                        unitId,
                        e.TribeId,
                        "command=" + e.AICommand.ToString()
                        + " target1="
                        + e.TargetValue1.ToString(CultureInfo.InvariantCulture)
                        + " target2="
                        + e.TargetValue2.ToString(CultureInfo.InvariantCulture));
                }
                catch (Exception exception)
                {
                    e.SkipOriginalFunction = false;
                    ContainOrdinaryEventFailure(
                        "native tribe target-order veto",
                        exception,
                        true);
                }
            }
        }

        /// <summary>
        /// True when <paramref name="tribeId"/> is the singleton selection
        /// tribe of the worker this feature currently leases, i.e. a tribe the
        /// native commit created for our own direct click and nobody else's.
        /// </summary>
        private bool TryGetOwnedSelectionTribeWorker(int tribeId, out int unitId)
        {
            unitId = 0;
            NativeSelectionLease lease = _selectionLease;
            if (tribeId <= 0
                || lease == null
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    lease.UnitId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (!SelectionLeaseMatches(lease, ref unit)
                || GameUnitManagerAPI.Instance.GetTribe(lease.UnitId) != tribeId
                || !IsOwnSelectionTribe(lease.UnitId, tribeId, ref unit))
            {
                return false;
            }
            unitId = lease.UnitId;
            return true;
        }

        /// <summary>
        /// Evidence only: a native tribe order reached the tribe our last
        /// confirmed selection lived in while no lease owns it any more (the
        /// engine already deselected the worker). Says whether the engine
        /// issues the move at all and in which tick relative to the loss.
        /// </summary>
        private void LogFormerSelectionTribeOrder(
            string kind,
            int tribeId,
            string detail)
        {
            if (tribeId <= 0
                || tribeId != _lastConfirmedSelectionTribeId
                || _lastConfirmedSelectionUnitId <= 0)
            {
                return;
            }
            int liveTribe = GameUnitManagerAPI.Instance.IsValid(
                    _lastConfirmedSelectionUnitId)
                ? GameUnitManagerAPI.Instance.GetTribe(_lastConfirmedSelectionUnitId)
                : -1;
            _info(
                "Worker militia observed a native tribe " + kind
                + " order for its former selection tribe after the engine had "
                + "deselected the worker: unit_id="
                + _lastConfirmedSelectionUnitId.ToString(CultureInfo.InvariantCulture)
                + " tribe=" + tribeId.ToString(CultureInfo.InvariantCulture)
                + " worker_tribe_now=" + liveTribe.ToString(CultureInfo.InvariantCulture)
                + " " + detail + ".");
        }

        private void LogVetoedNativeTribeOrder(
            string kind,
            int unitId,
            int tribeId,
            string detail)
        {
            string unit = SafeUnitName(unitId);
            _info(
                "Worker militia vetoed the native tribe " + kind
                + " order for its selected " + unit + ": unit_id="
                + unitId.ToString(CultureInfo.InvariantCulture)
                + " selection_tribe="
                + tribeId.ToString(CultureInfo.InvariantCulture)
                + " " + detail
                + "; the right-click is executed through the mission path.");
        }

        /// <summary>
        /// Evidence line for the one event that used to discard every manual
        /// order: the engine ended the worker's native selection while a
        /// right-click gesture was captured. Names the worker's AI state so
        /// the native reaction can be pinned from a log instead of guessed.
        /// </summary>
        private void LogNativeDeselectionDuringRightClick(int[] selectedNow)
        {
            RightClickGesture gesture = _pendingRightClickGesture;
            NativeSelectionLease lease = _selectionLease;
            if (gesture == null
                || lease == null
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    lease.UnitId,
                    out var pointer))
            {
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            _info(
                "Worker militia lost its native selection while a right-click "
                + "gesture was pending: unit=" + UnitName(unit.r_UnitChimp)
                + " unit_id=" + lease.UnitId.ToString(CultureInfo.InvariantCulture)
                + " gesture=" + gesture.Generation.ToString(CultureInfo.InvariantCulture)
                + " released=" + (gesture.Released ? "true" : "false")
                + " alive=" + unit.r_AliveState.ToString()
                + " ai_state=" + unit.r_AIState.ToString(CultureInfo.InvariantCulture)
                + " command_mode=" + SeInteropFieldAliases.CommandMode(ref unit).ToString(CultureInfo.InvariantCulture)
                + " selected_marker=" + unit.r_UnitHover.ToString(CultureInfo.InvariantCulture)
                + " selection_owner=" + unit.r_UnitSelected.ToString(CultureInfo.InvariantCulture)
                + " tribe=" + GameUnitManagerAPI.Instance.GetTribe(lease.UnitId)
                    .ToString(CultureInfo.InvariantCulture)
                + " work_link=" + DescribeWorkLink(lease.UnitId)
                + " native_selected_count="
                + (selectedNow == null ? 0 : selectedNow.Length).ToString(
                    CultureInfo.InvariantCulture)
                + " " + DescribeNativeSelectionGlobals()
                + ".");
        }

        /// <summary>
        /// Compact read-only dump of the pinned native selection globals (see
        /// the RVA constants). Never throws; failures become "native=unavailable".
        /// </summary>
        private string DescribeNativeSelectionGlobals()
        {
            try
            {
                if (_nativeModuleBase == IntPtr.Zero)
                {
                    return "native=unavailable";
                }
                long baseAddress = _nativeModuleBase.ToInt64();
                int hovered = Marshal.ReadInt32(new IntPtr(
                    baseAddress + NativeUnitManagerRva + NativeHoveredCountOffset));
                int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
                int selected = Marshal.ReadInt32(new IntPtr(
                    baseAddress + NativeUnitManagerRva
                    + SelectedCountOffsetForPlayer(localPlayer)));
                int mode = Marshal.ReadInt32(new IntPtr(
                    baseAddress + NativeUnitManagerRva + NativeUnitManagerModeOffset));
                int prevMode = Marshal.ReadInt32(new IntPtr(
                    baseAddress + NativeUnitManagerRva + NativeUnitManagerPrevModeOffset));
                return "native_state="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeSelectionStateRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " mode=" + mode.ToString(CultureInfo.InvariantCulture)
                    + "/" + prevMode.ToString(CultureInfo.InvariantCulture)
                    + " sel_tribe="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeSelectionTribeRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " sel_pending="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeSelectionPendingRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " sel_flag="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeSelectionFlagRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " cursor_kind="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeCursorKindRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " hovered=" + hovered.ToString(CultureInfo.InvariantCulture)
                    + " selected=" + selected.ToString(CultureInfo.InvariantCulture)
                    + " candidates="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeCandidateCountRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " app="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeAppModeRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + "/"
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeAppSubModeRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " hud_sub="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeHudSubModeRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + "/"
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeHudPrevSubModeRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " mapper="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeMapperItemRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " sel_on="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeSelectionOnRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + "/"
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeSelectionEstablishedRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " last_mouse="
                    + Marshal.ReadInt32(new IntPtr(baseAddress + NativeLastMouseStateRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " last_rd="
                    + Marshal.ReadByte(new IntPtr(baseAddress + NativeLastRightDownRva))
                        .ToString(CultureInfo.InvariantCulture)
                    + " last_ru="
                    + Marshal.ReadByte(new IntPtr(baseAddress + NativeLastRightUpRva))
                        .ToString(CultureInfo.InvariantCulture);
            }
            catch (Exception exception)
            {
                return "native=unavailable(" + exception.GetType().Name + ")";
            }
        }

        /// <summary>
        /// Identity-only check for a captured right-click packet: the same
        /// worker slot still holds the same alive militia worker of the local
        /// player. Used where the native selection may already be gone.
        /// </summary>
        private static bool RightClickGestureWorkerStillMatches(InputPacket packet)
        {
            if (packet == null || packet.SelectedWorkerId <= 0)
            {
                return false;
            }
            UnitSnapshot worker = CaptureUnit(packet.SelectedWorkerId);
            return worker != null
                && worker.GlobalId == packet.SelectedWorkerGlobalId
                && worker.Owner == packet.SelectedWorkerOwner
                && worker.Type == packet.SelectedWorkerType
                && worker.Owner == GamePlayerManagerAPI.Instance.GetLocalPlayerId()
                && IsMilitia(worker.Type);
        }

        private void OnUnitDelete(UnitDeleteEventArgs e)
        {
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            lock (_gate)
            {
                int unitId = unchecked((int)e.UnitId);
                _pendingWorkResumptionProofs.Remove(unitId);
                PendingDirectWorkCompletion pendingCompletion;
                if (_pendingDirectWorkCompletions.TryGetValue(
                        unitId,
                        out pendingCompletion))
                {
                    _pendingDirectWorkCompletions.Remove(unitId);
                    if (pendingCompletion.Command != null)
                    {
                        pendingCompletion.Command.DirectWorkCompletionPending =
                            false;
                        pendingCompletion.Command.OwnsCommandMode = false;
                    }
                }
                bool commandRemoved = _commands.Remove(unitId);
                if (commandRemoved)
                {
                    _info(
                        "Worker militia death cleanup: unit_id="
                        + unitId.ToString(CultureInfo.InvariantCulture)
                        + " command_removed=true replacement_allowed=true"
                        + " work_link_mutated=false return_move=false.");
                }
                if (_selectionLease != null
                    && _selectionLease.UnitId == unitId)
                {
                    if (_pendingSelectionWorkerId == unitId)
                    {
                        // The slot may be reused before the unstornierable
                        // native chore arrives. Retain only its identity proof;
                        // never restore fields through this deleted pointer.
                        RequestOutstandingSelectionCancellation(
                            "unit deletion while native selection was pending",
                            true,
                            true);
                    }
                    else
                    {
                        DeselectOwnedMilitia("unit deletion");
                        ReleaseNativeSelection("unit deletion");
                    }
                }
                if (_selectedWorkerId == unitId)
                {
                    _selectedWorkerId = 0;
                }
            }
        }

        private void ScanAndAdvance(int now)
        {
            List<UnitSnapshot> snapshots = CaptureUnits();
            var spatialIndex = new UnitSpatialIndex(snapshots);
            LogScanCensus(snapshots, spatialIndex, now);
            LogAiStateTransitions(snapshots);
            LearnWalkStates(snapshots);
            CollectMeasurementReferences(snapshots);
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            var commands = new List<CommandState>(_commands.Values);
            foreach (CommandState command in commands)
            {
                AdvanceCommand(command, snapshots, spatialIndex, now);
            }

            foreach (UnitSnapshot worker in snapshots)
            {
                if (!IsMilitia(worker.Type)
                    || worker.Owner != localPlayer
                    || _commands.ContainsKey(worker.Id)
                    || !CanEnterMilitiaCombat(worker.Type))
                {
                    continue;
                }
                UnitSnapshot target = FindBestEnemy(
                    worker,
                    spatialIndex,
                    GuardRadius(worker.Type),
                    null,
                    0);
                if (target != null)
                {
                    bool started = StartOrRetarget(
                        worker.Id,
                        worker.Type,
                        target.Id,
                        false,
                        now);
                    string unit = UnitName(worker.Type);
                    if (started
                        && _evidenceLogged.Add("command." + unit + ".autonomous"))
                    {
                        _info(RuntimeLogContract.WorkerMilitiaCommandEvidence(
                            unit,
                            "autonomous"));
                    }
                }
            }

            // Remember this scan's tiles last, so the next scan can tell which
            // workers the engine is actually walking.
            // Kept for every scan, not only while probes are running: the
            // walk-state learner below depends on it for the whole session.
            _previousWorkerPositions.Clear();
            foreach (UnitSnapshot snapshot in snapshots)
            {
                if (IsMilitia(snapshot.Type))
                {
                    _previousWorkerPositions[snapshot.Id] =
                        PackTile(snapshot.X, snapshot.Y);
                }
            }
        }

        private void RecordScanDuration(long startedTimestamp)
        {
            long elapsedTicks = Math.Max(
                0L,
                Stopwatch.GetTimestamp() - startedTimestamp);
            long elapsedMicroseconds = Stopwatch.Frequency <= 0
                ? 0
                : elapsedTicks * 1000000L / Stopwatch.Frequency;
            _scanDurationMicroseconds[_scanDurationSampleCount++] =
                elapsedMicroseconds;
            if (_scanDurationSampleCount < PerformanceWindowSamples)
            {
                return;
            }
            if (_performanceEvidenceLogged < MaxPerformanceEvidenceLogs)
            {
                var ordered = (long[])_scanDurationMicroseconds.Clone();
                Array.Sort(ordered);
                long total = 0;
                foreach (long sample in ordered)
                {
                    total += sample;
                }
                long mean = total / ordered.Length;
                int percentileIndex = Math.Min(
                    ordered.Length - 1,
                    Math.Max(
                        0,
                        (int)Math.Ceiling(ordered.Length * 0.99) - 1));
                long p99 = ordered[percentileIndex];
                _performanceEvidenceLogged++;
                _info(RuntimeLogContract.WorkerMilitiaPerformanceEvidence(
                    ordered.Length,
                    mean,
                    p99,
                    mean <= 1000L && p99 <= 3000L));
            }
            _scanDurationSampleCount = 0;
        }

        /// <summary>
        /// Drops every map-scoped observation before the next map can publish
        /// evidence. None of these values owns gameplay state.
        /// </summary>
        /// <remarks>
        /// The old counters lived for the whole process. Once the first map
        /// consumed an animation or cursor budget, later canaries produced no
        /// evidence at all. Worse, the cone probe could briefly compare a new
        /// selection with unit/tile snapshots from the previous map. Resetting
        /// the immutable samples and all budgets at the closed map gate keeps
        /// measurements map-local without changing any command mechanism.
        /// </remarks>
        private void ResetMapMeasurementStateLocked()
        {
            _animationProbesLogged = 0;
            _cursorSamplesLogged = 0;
            _cursorReplaysLogged = 0;
            _commandClassEvidenceLogged = 0;
            _commandClassEvidenceContexts.Clear();
            _animationTraceLogged = 0;
            _animationTraceCommandId = 0;
            _animationTraceGeneration = 0;
            _saveRestoreLogged = 0;
            _hunterAnimationProbesLogged = 0;
            _aiTransitionsLogged = 0;
            _lastScanEnemyPairs = -1;
            _nextScanCensusLogTick = 0;
            _previousWorkerPositions.Clear();
            _aiStateHistory.Clear();
            _observedWalkState.Clear();
            _walkStateCounts.Clear();
            _observedWalkSprite.Clear();
            _walkSpriteCounts.Clear();
            Volatile.Write(
                ref _measureMilitiaUnits,
                new Dictionary<int, ConeUnitSample>());
            Volatile.Write(ref _measureSoldier, null);
            Volatile.Write(ref _measureOwnUnitTiles, Array.Empty<long>());
        }

        private void AdvanceCommand(
            CommandState command,
            List<UnitSnapshot> snapshots,
            UnitSpatialIndex spatialIndex,
            int now)
        {
            UnitSnapshot worker = spatialIndex.FindById(
                command.WorkerUnitId);
            if (worker == null || !IsMilitia(worker.Type)
                || worker.GlobalId != command.WorkerGlobalId
                || worker.Type != command.WorkerType
                || worker.Owner != command.WorkerOwner
                || worker.Owner
                    != GamePlayerManagerAPI.Instance.GetLocalPlayerId()
                || !CommandMatchesLiveWorkerProvenance(
                    command,
                    command.WorkerUnitId))
            {
                AbandonCommandAfterProvenanceChange(
                    command,
                    "identity, owner, type or command mode changed");
                return;
            }
            if (!CommandTribeProvenanceMatches(
                    command,
                    command.WorkerUnitId))
            {
                AbandonCommandAfterProvenanceChange(
                    command,
                    "foreign tribe change");
                return;
            }
            // Ein heimatloser Einsatz hat keinen Arbeitsplatz, der verloren
            // gehen koennte. Ihn hier abzuraeumen wuerde ihn in demselben Takt
            // beenden, in dem er entstanden ist - der Arbeiter waere wieder
            // wehrlos.
            if (!command.Homeless)
            {
                NoteWorkplaceLoss(command);
                if (command.WorkplaceLost)
                {
                    CompleteDirectWork(
                        command,
                        worker,
                        "workplace_lost",
                        false);
                    return;
                }
            }

            if (command.Phase == MissionPhase.DirectWorkPending)
            {
                PendingDirectWorkCompletion pending;
                if (!command.DirectWorkCompletionPending
                    || !_pendingDirectWorkCompletions.TryGetValue(
                        command.WorkerUnitId,
                        out pending)
                    || !ReferenceEquals(pending.Command, command))
                {
                    // Die Buchhaltung zwischen Befehl und Uebergabeliste ist
                    // auseinandergelaufen. Das ist ein Fehler in EINEM Einsatz;
                    // AdvanceCommand laeuft je Takt, und eine Ausnahme hier
                    // beendet den Mod fuer die ganze Sitzung.
                    if (_evidenceLogged.Add("direct_work_ownership_lost"))
                    {
                        _warning(
                            "Worker militia lost its pending direct-work "
                            + "ownership for unit_id="
                            + command.WorkerUnitId.ToString(
                                CultureInfo.InvariantCulture)
                            + "; that single mission is given up, the militia "
                            + "keeps running.");
                    }
                    AbandonCommandAfterProvenanceChange(
                        command,
                        "direct-work bookkeeping lost");
                    return;
                }
                return;
            }

            if (command.Phase == MissionPhase.Outbound)
            {
                UnitSnapshot outboundThreat = CanEnterMilitiaCombat(
                        command.WorkerType)
                    ? FindBestEnemy(
                        worker,
                        spatialIndex,
                        GuardRadius(command.WorkerType),
                        null,
                        0)
                    : null;
                if (outboundThreat != null)
                {
                    // Entscheidung des Eigentuemers, 30.08.2026: ein Gegner auf
                    // dem WEG darf nicht ignoriert werden.
                    //
                    // Vorher war der Kampfanker bei einem Bewegungsbefehl das
                    // ZIEL, und BeginFight hielt ihn dort fest. Ein Gegner auf
                    // halber Strecke lag damit ausserhalb der Verfolgungsleine
                    // - beim Holzfaeller sind das 9 Kacheln - und wurde im
                    // naechsten Takt wieder verworfen. Der Arbeiter marschierte
                    // an ihm vorbei.
                    //
                    // Der Anker wandert deshalb an die Stelle, an der der Kampf
                    // beginnt. Die Leine bleibt damit erhalten, sie haengt nur
                    // nicht mehr am Ziel eines Marsches, den der Gegner
                    // unterbrochen hat.
                    command.CombatAnchorX = worker.CombatX;
                    command.CombatAnchorY = worker.CombatY;
                    BeginFight(command, worker, outboundThreat, false, now);
                    return;
                }
                long destinationDistance = DistanceSquared(
                    worker.X,
                    worker.Y,
                    command.ManualDestinationX,
                    command.ManualDestinationY);
                int arrival = GeneratedWorkerMilitiaContract.ReturnArrivalRadius;
                if (destinationDistance <= (long)arrival * arrival)
                {
                    BeginHolding(command, now);
                    return;
                }
                LogMovementAnimationProbe(
                    command,
                    worker,
                    snapshots,
                    "outbound");
                if (HasReached(now, command.NextMoveTick)
                    && ShouldIssueMove(
                        command,
                        worker,
                        command.ManualDestinationX,
                        command.ManualDestinationY,
                        now))
                {
                    if (ShouldAbortStalledManualMove(
                            command,
                            worker,
                            command.ManualDestinationX,
                            command.ManualDestinationY,
                            now))
                    {
                        CompleteDirectWork(
                            command,
                            worker,
                            "manual_destination_unreachable",
                            false);
                        return;
                    }
                    MoveWorker(
                        command,
                        command.ManualDestinationX,
                        command.ManualDestinationY,
                        now,
                        "outbound");
                }
                return;
            }

            if (command.Phase == MissionPhase.Holding)
            {
                UnitSnapshot newThreat = CanEnterMilitiaCombat(
                        command.WorkerType)
                    ? FindBestEnemy(
                        worker,
                        spatialIndex,
                        GuardRadius(command.WorkerType),
                        null,
                        0)
                    : null;
                if (newThreat != null)
                {
                    command.PausedHoldRemainingMilliseconds =
                        RemainingMilliseconds(
                            now,
                            command.HoldDeadlineTick,
                            GeneratedWorkerMilitiaContract
                                .HoldDurationMilliseconds);
                    command.ResumeHoldAfterCombat =
                        WorkerMilitiaMissionRules.ShouldResumePausedHold(
                            command.PausedHoldRemainingMilliseconds);
                    BeginFight(command, worker, newThreat, false, now);
                    return;
                }
                long destinationDistance = DistanceSquared(
                    worker.X,
                    worker.Y,
                    command.ManualDestinationX,
                    command.ManualDestinationY);
                int arrival = GeneratedWorkerMilitiaContract.ReturnArrivalRadius;
                if (destinationDistance > (long)arrival * arrival)
                {
                    command.ManualDestinationReached = false;
                    command.Phase = MissionPhase.Outbound;
                    command.HoldDeadlineTick = 0;
                    // The worker drifted off its hold tile; send it back with a
                    // fresh order even though the destination is unchanged.
                    command.HasIssuedMove = false;
                    MoveWorker(
                        command,
                        command.ManualDestinationX,
                        command.ManualDestinationY,
                        now,
                        "holding correction");
                    return;
                }
                if (HasReached(now, command.HoldDeadlineTick))
                {
                    string unit = UnitName(command.WorkerType);
                    if (_evidenceLogged.Add("hold_completed." + unit))
                    {
                        _info(RuntimeLogContract.WorkerMilitiaHoldCompletedEvidence(
                            unit));
                    }
                    CompleteDirectWork(
                        command,
                        worker,
                        "hold_no_contact",
                        false);
                }
                return;
            }

            if (!CanEnterMilitiaCombat(command.WorkerType))
            {
                // A persisted or already-running hunter mission may reach this
                // point after a contract downgrade. It may resume an owned
                // destination or return to work, but it must not use an
                // uncalibrated range to acquire, approach or damage a target.
                RetargetOrResume(
                    command,
                    worker,
                    spatialIndex,
                    now,
                    command.TargetUnitId);
                return;
            }

            UnitSnapshot target = spatialIndex.FindById(
                command.TargetUnitId);
            if (target == null
                || target.GlobalId != command.TargetGlobalId
                || !IsEnemyPlayerUnit(worker.Owner, target.Owner)
                || OutsidePursuit(command, target))
            {
                int excludedTarget = target != null
                        && target.GlobalId != command.TargetGlobalId
                    ? 0
                    : command.TargetUnitId;
                RetargetOrResume(
                    command,
                    worker,
                    spatialIndex,
                    now,
                    excludedTarget);
                return;
            }

            int attackRange = AttackRange(command.WorkerType);
            long distance = DistanceSquared(
                worker.CombatX,
                worker.CombatY,
                target.CombatX,
                target.CombatY);
            if (distance > (long)attackRange * attackRange)
            {
                LogMovementAnimationProbe(
                    command,
                    worker,
                    snapshots,
                    "closing_on_target");
                if (HasReached(now, command.NextMoveTick))
                {
                    int destinationX;
                    int destinationY;
                    ComputeApproachTile(
                        worker,
                        target,
                        attackRange,
                        out destinationX,
                        out destinationY);
                    if (ShouldIssueMove(
                            command,
                            worker,
                            destinationX,
                            destinationY,
                            now))
                    {
                        if (ShouldAbortStalledManualMove(
                                command,
                                worker,
                                destinationX,
                                destinationY,
                                now))
                        {
                            CompleteDirectWork(
                                command,
                                worker,
                                "manual_target_unreachable",
                                false);
                            return;
                        }
                        MoveWorker(
                            command,
                            destinationX,
                            destinationY,
                            now,
                            "pursuit");
                    }
                }
                return;
            }
            if (!HasReached(now, command.NextAttackTick))
            {
                return;
            }
            FaceTarget(command.WorkerUnitId, worker, target);
            if (command.WorkerType == eChimps.CHIMP_TYPE_HUNTER)
            {
                FireHunterArrow(command, worker, target, now);
            }
            else
            {
                StrikeWithWoodcutter(command, target, now);
            }
        }

        private bool StartOrRetarget(
            int workerId,
            eChimps workerType,
            int targetId,
            bool manual,
            int now)
        {
            if (!CanEnterMilitiaCombat(workerType))
            {
                if (_evidenceLogged.Add(
                        "combat_calibration_required." + workerType))
                {
                    _warning(
                        "Worker militia refused hunter combat because its "
                        + "native range metric has not been calibrated from a "
                        + "reviewed runtime observation. Movement and "
                        + "selection remain available.");
                }
                return false;
            }
            UnitSnapshot target = CaptureUnit(targetId);
            if (target == null
                || !CanDamage(workerType, target.Type)
                || !IsValidMapTile(target.X, target.Y))
            {
                return false;
            }
            CommandState existing;
            if (_commands.TryGetValue(workerId, out existing))
            {
                if (!EnsureCommandMode(existing, false))
                {
                    return false;
                }
                existing.TargetUnitId = targetId;
                existing.TargetGlobalId = target.GlobalId;
                existing.Manual = manual;
                existing.ExplicitTarget = manual;
                existing.Phase = MissionPhase.Fighting;
                if (manual)
                {
                    existing.HasManualDestination = false;
                    existing.ManualDestinationReached = false;
                    existing.ResumeHoldAfterCombat = false;
                    existing.PausedHoldRemainingMilliseconds = 0;
                }
                existing.HoldDeadlineTick = 0;
                UnitSnapshot currentWorker = CaptureUnit(workerId);
                if (currentWorker != null)
                {
                    existing.CombatAnchorX = currentWorker.CombatX;
                    existing.CombatAnchorY = currentWorker.CombatY;
                }
                existing.NextMoveTick = now;
                existing.NextAttackTick = now;
                ResetMovementStall(existing, now);
                return true;
            }
            UnitSnapshot worker = CaptureUnit(workerId);
            if (worker == null
                || !IsMilitia(worker.Type)
                || !IsValidMapTile(worker.X, worker.Y))
            {
                return false;
            }
            CommandState command = CreateCommand(worker, manual);
            if (command == null)
            {
                return false;
            }
            // Erwerb und Bindung massen bis zum 30.08.2026 von VERSCHIEDENEN
            // Punkten: ScanAndAdvance sucht mit command=null, also ohne Leine
            // und gemessen vom Arbeiter; RetargetOrResume prueft danach gegen
            // den Anker am Arbeitsplatz. Ein Arbeiter fernab seiner Huette fand
            // damit staendig Ziele, die der naechste Takt sofort als ausserhalb
            // der Leine verwarf - Einsatz auf, Einsatz zu, in jedem Scan.
            //
            // Der Spiellauf vom 30.08. zeigte 50.038 begonnene Einsaetze und
            // 49.875 sofortige "combat_clear" - dieselbe Zahl, und 22 MB
            // Protokoll. Deshalb wird die Leine jetzt schon hier angelegt, VOR
            // dem Schreiben des Befehlsmodus. Ein Spielerbefehl bleibt
            // ungeleint: UsesLocalPursuitLeash ist fuer manual+explicit falsch.
            command.ExplicitTarget = manual;
            if (!manual)
            {
                // Acquisition is measured from the worker, so retention must
                // be anchored at that same contact point. Hunters and
                // woodcutters routinely work far away from their huts; using
                // the workplace here rejected an enemy standing beside the
                // worker merely because both were outside the hut-centred
                // pursuit circle.
                command.CombatAnchorX = worker.CombatX;
                command.CombatAnchorY = worker.CombatY;
            }
            if (OutsidePursuit(command, target))
            {
                if (_evidenceLogged.Add("engage_outside_leash." + workerType))
                {
                    _info(
                        "Worker militia left a " + UnitName(workerType)
                        + " at work: the nearest enemy is inside its guard "
                        + "radius but outside the pursuit leash of its "
                        + "contact point. Starting there would end the mission in "
                        + "the same tick.");
                }
                return false;
            }
            if (!EnsureCommandMode(command, false))
            {
                return false;
            }
            command.TargetUnitId = targetId;
            command.TargetGlobalId = target.GlobalId;
            command.ExplicitTarget = manual;
            command.Phase = MissionPhase.Fighting;
            command.ManualDestinationReached = false;
            command.HoldDeadlineTick = 0;
            command.ResumeHoldAfterCombat = false;
            command.PausedHoldRemainingMilliseconds = 0;
            command.NextAttackTick = now;
            command.NextMoveTick = now;
            ResetMovementStall(command, now);
            _pendingWorkResumptionProofs.Remove(workerId);
            _commands.Add(workerId, command);
            // Ungedrosselt hat diese Zeile im Lauf vom 30.08. rund 50.000 Mal
            // geschrieben und das Protokoll auf 22 MB getrieben - die
            // eigentlichen Messwerte waren darin nicht mehr zu finden. Ein
            // Beleg je Arbeiterart und Befehlsart genuegt.
            if (_evidenceLogged.Add(
                    "interrupted_work." + workerType + "." + manual))
            {
                _info(
                    "Worker militia " + UnitName(workerType)
                    + " interrupted work for a "
                    + (manual ? "native single-selection order" : "nearby enemy")
                    + ".");
            }
            return true;
        }

        private CommandState CreateCommand(UnitSnapshot worker, bool manual)
        {
            if (worker == null)
            {
                return null;
            }
            OccupancyProvenance occupancy;
            NativeSelectionLease lease = _selectionLease;
            bool useSelectionLease = lease != null
                && lease.UnitId == worker.Id
                && lease.GlobalId == worker.GlobalId
                && lease.Owner == worker.Owner
                && lease.Type == worker.Type;
            if (useSelectionLease)
            {
                if (!WorkerOccupancyMatches(
                        worker.Id,
                        worker.GlobalId,
                        worker.Owner,
                        worker.Type,
                        lease.Occupancy))
                {
                    return null;
                }
                occupancy = CopyOccupancy(lease.Occupancy);
            }
            else if (!TryCaptureWorkerOccupancy(
                    worker.Id,
                    worker.GlobalId,
                    worker.Owner,
                    worker.Type,
                    out occupancy))
            {
                occupancy = null;
            }
            // Vorbelegt, weil der Kurzschluss unten die out-Parameter sonst
            // ungesetzt laesst.
            int workplaceAnchorX = 0;
            int workplaceAnchorY = 0;
            bool homeless = occupancy == null
                || !TryGetWorkplaceAnchor(
                    occupancy,
                    out workplaceAnchorX,
                    out workplaceAnchorY);
            if (homeless)
            {
                // Ein Arbeiter ohne lebenden Arbeitsplatz laeuft unter Vanillas
                // Regie zum Bergfried und loest sich dort am Feuer zum Bauern
                // auf. Anwaehlbar ist er nicht - TryArmNativeSelection verlangt
                // weiterhin einen Arbeitsplatz, und ein Spielerbefehl setzt
                // eine Anwahl voraus. Wehrhaft soll er unterwegs trotzdem sein:
                // genau dafuer existiert eine Arbeitermiliz. Also nur der
                // autonome Weg, und der Kampfanker ist sein eigener Standort
                // statt eines Gebaeudes, das es nicht mehr gibt.
                if (manual)
                {
                    return null;
                }
                occupancy = null;
                workplaceAnchorX = worker.CombatX;
                workplaceAnchorY = worker.CombatY;
            }
            var command = new CommandState
            {
                Generation = _commandGeneration == long.MaxValue
                    ? (_commandGeneration = 1)
                    : ++_commandGeneration,
                WorkerUnitId = worker.Id,
                WorkerGlobalId = worker.GlobalId,
                WorkerOwner = worker.Owner,
                WorkerType = worker.Type,
                OriginX = worker.X,
                OriginY = worker.Y,
                OriginalWorkLink = worker.WorkLink,
                OriginalTribeId = worker.TribeId,
                Manual = manual,
                Phase = MissionPhase.Fighting,
                CombatAnchorX = workplaceAnchorX,
                CombatAnchorY = workplaceAnchorY,
                NextAttackTick = SimulationNowMilliseconds(),
                NextMoveTick = SimulationNowMilliseconds(),
                Occupancy = occupancy,
                Homeless = homeless,
            };
            if (useSelectionLease)
            {
                // The lease is the pre-selection provenance authority. The
                // normal native selection path is accepted only while the
                // live work link and tribe continue to equal these values.
                command.OriginX = lease.OriginalX;
                command.OriginY = lease.OriginalY;
                command.OriginalWorkLink = lease.OriginalWorkLink;
                command.OriginalTribeId = lease.OriginalTribeId;
            }
            return command;
        }

        private static bool TryGetWorkplaceAnchor(
            OccupancyProvenance occupancy,
            out int tileX,
            out int tileY)
        {
            tileX = 0;
            tileY = 0;
            if (occupancy == null
                || !GameBuildingManagerAPI.Instance.TryGetBuildingByIdEx(
                    occupancy.BuildingId,
                    out var pointer))
            {
                return false;
            }
            ref GameBuilding building = ref pointer.AsRef();
            if (building.r_AliveState != AliveState.IsAlive
                || unchecked((int)building.r_GlobalId)
                    != occupancy.BuildingGlobalId
                || building.r_BuildingType != occupancy.BuildingType
                || building.r_PlayerIdOwner != occupancy.BuildingOwner)
            {
                return false;
            }
            tileX = unchecked((short)building.r_WorldPositionX)
                / WorldTilesPerLocalTile;
            tileY = unchecked((short)building.r_WorldPositionY)
                / WorldTilesPerLocalTile;
            return IsValidMapTile(tileX, tileY);
        }

        /// <summary>
        /// Darf dieser Einsatz diese Einheit noch befehligen?
        /// </summary>
        /// <remarks>
        /// Bis zum 27.08.2026 verlangte diese Frage zusaetzlich, dass sich die
        /// ARBEITSBINDUNG nicht geaendert hat - und das ist eine andere Frage.
        /// Wogegen hier geschuetzt werden muss, ist, an eine FREMDE Einheit zu
        /// schreiben; das leistet die Identitaet (lebt, gleiche globale
        /// Kennung, gleicher Besitzer, gleicher Typ) vollstaendig. Ob die
        /// Werkstatt des Arbeiters noch steht, sagt darueber nichts.
        ///
        /// Der Unterschied ist fuer die Freigabe entscheidend: ein verlorener
        /// Arbeitsplatz setzt WorkplaceLost und beendet den Auftrag am
        /// sicheren nativen Rand. Besitzer-, Typ-, Generations- oder fremde
        /// Tribe-Aenderungen laufen dagegen nie als Arbeitsplatzverlust
        /// weiter und duerfen keine alte Arbeitsbindung restaurieren.
        /// </remarks>
        private static bool CommandMatchesLiveWorkerProvenance(
            CommandState command,
            int unitId)
        {
            if (command == null
                || command.WorkerUnitId != unitId
                || !command.OwnsCommandMode
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            return unit.r_AliveState == AliveState.IsAlive
                && unchecked((int)unit.r_GlobalId) == command.WorkerGlobalId
                && unit.r_ControllableForPlayerId == command.WorkerOwner
                && unit.r_UnitChimp == command.WorkerType
                && SeInteropFieldAliases.CommandMode(ref unit) == 1;
        }

        /// <summary>
        /// Merkt einmalig, dass der Arbeitsplatz des Arbeiters waehrend des
        /// Einsatzes verschwunden ist. Der Auftrag wird am naechsten sicheren
        /// nativen Rand freigegeben, damit Vanilla den Arbeiter neu zuweist.
        /// </summary>
        private void NoteWorkplaceLoss(CommandState command)
        {
            if (command == null || command.WorkplaceLost || command.Homeless)
            {
                return;
            }
            // Identitaetswache zuerst. Ein toter oder wiederverwendeter
            // Einheitenplatz laesst CommandWorkProvenanceMatches ebenfalls
            // scheitern, hat aber mit einem verlorenen Arbeitsplatz nichts zu
            // tun - die Meldung "Arbeitsplatz verloren, Arbeiter weiter im
            // Einsatz" waere schlicht falsch, und die Aufrufer verwerfen den
            // Einsatz unmittelbar danach ohnehin ueber die Identitaet.
            if (!CommandIdentityMatchesLiveWorker(
                    command,
                    command.WorkerUnitId))
            {
                return;
            }
            if (CommandWorkProvenanceMatches(command, command.WorkerUnitId))
            {
                return;
            }
            command.WorkplaceLost = true;
            _warning(
                "Worker militia lost the workplace of a worker that is still on "
                + "duty: unit_id="
                + command.WorkerUnitId.ToString(CultureInfo.InvariantCulture)
                + " type=" + UnitName(command.WorkerType)
                + " original_work_link="
                + command.OriginalWorkLink.ToString(CultureInfo.InvariantCulture)
                + " live_work_link=" + DescribeWorkLink(command.WorkerUnitId)
                + ". The mission is released at the next native boundary so "
                + "Vanilla can reassign the worker.");
        }

        private static bool CommandIdentityMatchesLiveWorker(
            CommandState command,
            int unitId)
        {
            if (command == null
                || command.WorkerUnitId != unitId
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            return unit.r_AliveState == AliveState.IsAlive
                && unchecked((int)unit.r_GlobalId) == command.WorkerGlobalId
                && unit.r_ControllableForPlayerId == command.WorkerOwner
                && unit.r_UnitChimp == command.WorkerType;
        }

        private static bool CommandWorkProvenanceMatches(
            CommandState command,
            int unitId)
        {
            int liveWorkLink;
            if (command == null
                || !TryReadExposedUnitInt(
                    unitId,
                    "r_LinkedProductionBuildingId",
                    out liveWorkLink))
            {
                // Gone units do not match a provenance; they also must not
                // throw here, because every combat and movement path asks.
                return false;
            }
            return liveWorkLink == command.OriginalWorkLink
                && WorkerOccupancyMatches(
                    unitId,
                    command.WorkerGlobalId,
                    command.WorkerOwner,
                    command.WorkerType,
                    command.Occupancy);
        }

        /// <summary>
        /// Employment-state proof for taking command-mode ownership.
        /// Ordinary workers must still own their exact captured workplace
        /// slot. A homeless worker must still own no live workplace slot; its
        /// identity and tribe are checked separately by the caller.
        /// </summary>
        private static bool CommandEmploymentStateMatches(
            CommandState command,
            int unitId)
        {
            if (command == null)
            {
                return false;
            }
            if (!command.Homeless)
            {
                return CommandWorkProvenanceMatches(command, unitId);
            }
            OccupancyProvenance unexpectedLiveOccupancy;
            return !TryCaptureWorkerOccupancy(
                unitId,
                command.WorkerGlobalId,
                command.WorkerOwner,
                command.WorkerType,
                out unexpectedLiveOccupancy);
        }

        private static bool CommandTribeProvenanceMatches(
            CommandState command,
            int unitId)
        {
            return command != null
                && CommandIdentityMatchesLiveWorker(command, unitId)
                && TribeProvenanceMatches(
                    unitId,
                    command.OriginalTribeId,
                    out _);
        }

        /// <summary>
        /// Decides whether a militia worker's live tribe still matches the
        /// provenance captured before it was leased or commanded.
        /// </summary>
        /// <remarks>
        /// Measured on the 2.7 build (see <see cref="WorkerMilitiaNativeLayout"/>;
        /// RVAs in comments of this file are 2.7 values unless marked 2.80).
        /// The non-Shift mouse-up commit at RVA 0x1901F0 marks every selected
        /// unit of the local player in the manager+0x74 bitset, allocates a
        /// fresh tribe slot through RVA 0x11C050 and queues chore 0x10. The
        /// chore executor at RVA 0x18FF90 writes +0xAE/+0xB0 for every marked
        /// unit, re-initialises that tribe through RVA 0x118B80 (owner,
        /// alive=2, members=0) and RVA 0x11C3B0 then assigns EVERY alive,
        /// unblocked unit whose selection owner equals the player through
        /// c_game_unit_assign_tribe (RVA 0x11C210). There is no unit-type
        /// filter, so a command-mode worker is grouped exactly like a soldier
        /// and r_TribeId goes 0 -> fresh tribe on the very first confirmed
        /// selection. Native deselection (RVA 0x199300 for one unit, the chore
        /// executor at RVA 0x199430 for the player) removes the unit again
        /// through c_game_tribe_remove_unit (RVA 0x122D40), which resets
        /// r_TribeId to 0. The ordinary "click elsewhere" path is different:
        /// RVA 0x1992E0 queues chore 0x0F, whose executor is RVA 0x199300 with
        /// unit 0, and that branch only clears +0xAE for every unit of the
        /// player - each unit keeps its tribe, exactly as soldiers keep their
        /// group between selections. A militia worker therefore legitimately
        /// carries a non-zero tribe id from its first confirmed selection
        /// until that singleton tribe is dissolved again, either by the
        /// per-unit native clear or by <see cref="TryDissolveStaleSelectionTribe"/>.
        /// The tribe is unambiguous in both states: it is alive, owned by the
        /// worker's player, led by the worker and holds no other member.
        /// Neither routine touches r_LinkedProductionBuildingId, which stays
        /// an exact-match requirement at every call site.
        /// </remarks>
        private static bool TribeProvenanceMatches(
            int unitId,
            int originalTribeId,
            out int liveTribeId)
        {
            liveTribeId = GameUnitManagerAPI.Instance.GetTribe(unitId);
            if (liveTribeId == originalTribeId)
            {
                return true;
            }
            if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            return IsOwnSelectionTribe(unitId, liveTribeId, ref unit);
        }

        /// <summary>
        /// True when <paramref name="tribeId"/> is the singleton selection
        /// tribe the native commit created for this unit: alive, owned by the
        /// unit's own player, led by the unit itself and holding no other
        /// member. Anything else (a foreign multi-selection, a tribe of
        /// another player, a pre-existing group) is not accepted.
        /// </summary>
        private static bool IsOwnSelectionTribe(
            int unitId,
            int tribeId,
            ref GameUnit unit)
        {
            // Deliberately without the tribe-manager API: controlling or even
            // inspecting militia workers through the tribe manager is what the
            // discarded first implementation did, and the contract forbids that
            // whole API here. The pinned unit fields carry the same proof. A
            // militia worker only ever receives a tribe from the native
            // selection commit, because this feature refuses to lease a worker
            // that already belongs to one; so a non-zero tribe on a unit that
            // the local player currently holds selected is that commit's own.
            return tribeId > 0
                && unit.r_UnitHover != 0
                && unit.r_UnitSelected != 0
                && unit.r_UnitSelected == unit.r_ControllableForPlayerId;
        }

        /// <summary>
        /// Dissolves the singleton selection tribe the game left behind after
        /// it ended our worker's selection itself (chore 0x0F clears +0xAE but
        /// keeps the tribe). Uses the pinned per-unit clear at RVA 0x199300,
        /// which removes the unit from its tribe through
        /// c_game_tribe_remove_unit and skips the already-cleared selection
        /// owner and counter on its own. Never touches a unit that is still
        /// selected (the committed path owns that) or a tribe that is not the
        /// worker's own singleton.
        /// </summary>
        /// <returns>
        /// True when the worker's tribe equals <paramref name="originalTribeId"/>
        /// afterwards, false when there was nothing this method may touch.
        /// </returns>
        private bool TryDissolveStaleSelectionTribe(
            int unitId,
            int owner,
            int originalTribeId,
            ref GameUnit unit,
            string reason)
        {
            int tribeId = GameUnitManagerAPI.Instance.GetTribe(unitId);
            if (tribeId == originalTribeId)
            {
                return true;
            }
            // The selection owner is already cleared here, so the tribe cannot
            // be proved from the unit's selection fields. Only a tribe this
            // feature itself watched the native commit create for exactly this
            // worker may be dissolved; anything else stays untouched.
            if (unit.r_UnitSelected != 0
                || tribeId <= 0
                || unitId != _lastConfirmedSelectionUnitId
                || tribeId != _lastConfirmedSelectionTribeId)
            {
                return false;
            }
            // Both of the following used to throw, on a path the mouse
            // postfix, the run postfix and the R3 events all reach - so either
            // one stopped the whole feature for the session. Neither is a
            // contract violation: this is a Try- method whose documented false
            // means "there was nothing here this method may touch", and the
            // callers already ignore the result. Declining leaves the stale
            // selection tribe in place, which the feature has tolerated since
            // the tribe-provenance fix of 2026-08-19.
            if (_nativePlayerSelectionClear == null
                || _nativeModuleBase == IntPtr.Zero)
            {
                if (_evidenceLogged.Add("dissolve_unavailable"))
                {
                    _warning(
                        "Worker militia cannot dissolve a stale selection tribe: "
                        + "the pinned per-unit selection clear is unavailable. "
                        + "The tribe is left alone.");
                }
                return false;
            }
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            if (localPlayer < 1 || localPlayer > 8 || owner != localPlayer)
            {
                if (_evidenceLogged.Add("dissolve_foreign_player"))
                {
                    _warning(
                        "Worker militia leaves stale selection tribes alone "
                        + "because the selection owner is not the valid local "
                        + "player (local_player="
                        + localPlayer.ToString(CultureInfo.InvariantCulture)
                        + " owner="
                        + owner.ToString(CultureInfo.InvariantCulture) + ").");
                }
                return false;
            }
            int hoveredBefore = GetPinnedNativeHoveredCount();
            int selectedBefore = GetPinnedNativeSelectedCount();
            if (hoveredBefore < 0 || selectedBefore < 0)
            {
                // Without trustworthy counters the read-back below cannot say
                // anything, so nothing is written at all.
                return false;
            }
            IntPtr manager = new IntPtr(
                _nativeModuleBase.ToInt64() + NativeUnitManagerRva);
            _nativePlayerSelectionClear(manager, owner, unitId, 0);
            int tribeAfter = GameUnitManagerAPI.Instance.GetTribe(unitId);
            if (tribeAfter != originalTribeId
                || unit.r_UnitSelected != 0
                || GetPinnedNativeHoveredCount() != hoveredBefore
                || GetPinnedNativeSelectedCount() != selectedBefore)
            {
                // Try- semantics again: report and decline. The dissolve call
                // already ran; stopping the feature would not undo it.
                if (_evidenceLogged.Add("dissolve_readback_failed"))
                {
                    _warning(
                        "Worker militia stale-tribe dissolve did not read back "
                        + "as expected during " + reason + ": tribe_before="
                        + tribeId.ToString(CultureInfo.InvariantCulture)
                        + " tribe_after="
                        + tribeAfter.ToString(CultureInfo.InvariantCulture)
                        + " expected="
                        + originalTribeId.ToString(CultureInfo.InvariantCulture)
                        + ". The tribe is left as it is.");
                }
                return false;
            }
            _info(
                "Worker militia dissolved the stale native selection tribe "
                + tribeId.ToString(CultureInfo.InvariantCulture)
                + " during " + reason + "; pre-selection tribe "
                + originalTribeId.ToString(CultureInfo.InvariantCulture)
                + " restored.");
            return true;
        }

        private bool EnsureCommandMode(
            CommandState command,
            bool allowPersistedOwnedValue)
        {
            if (command == null
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    command.WorkerUnitId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (unit.r_AliveState != AliveState.IsAlive
                || unchecked((int)unit.r_GlobalId) != command.WorkerGlobalId
                || unit.r_ControllableForPlayerId != command.WorkerOwner
                || unit.r_UnitChimp != command.WorkerType
                || !CommandEmploymentStateMatches(
                    command,
                    command.WorkerUnitId)
                || !CommandTribeProvenanceMatches(
                    command,
                    command.WorkerUnitId))
            {
                return false;
            }
            if (command.OwnsCommandMode)
            {
                if (SeInteropFieldAliases.CommandMode(ref unit) == 1)
                {
                    return true;
                }
                command.OwnsCommandMode = false;
                _warning(
                    "Worker militia lost command-mode ownership while a mission "
                    + "was active; the foreign value was preserved.");
                return false;
            }
            NativeSelectionLease selection = _selectionLease;
            bool ownedBySelection = selection != null
                && selection.UnitId == command.WorkerUnitId
                && SelectionLeaseMatches(selection, ref unit)
                && SeInteropFieldAliases.CommandMode(ref unit) == 1;
            if (ownedBySelection)
            {
                command.OriginalCommandModeValue =
                    selection.OriginalCommandModeValue;
                command.OwnsCommandMode = true;
                return true;
            }
            if (allowPersistedOwnedValue && SeInteropFieldAliases.CommandMode(ref unit) == 1)
            {
                if (command.OriginalCommandModeValue != 0)
                {
                    return false;
                }
                command.OwnsCommandMode = true;
                return true;
            }
            if (SeInteropFieldAliases.CommandMode(ref unit) != 0)
            {
                return false;
            }
            command.OriginalCommandModeValue = SeInteropFieldAliases.CommandMode(ref unit);
            SeInteropFieldAliases.CommandMode(ref unit) = 1;
            if (SeInteropFieldAliases.CommandMode(ref unit) != 1)
            {
                SeInteropFieldAliases.CommandMode(ref unit) = command.OriginalCommandModeValue;
                return false;
            }
            command.OwnsCommandMode = true;
            return true;
        }

        private void RestoreOwnedCommandMode(
            CommandState command,
            string reason)
        {
            if (command == null || !command.OwnsCommandMode)
            {
                return;
            }
            if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    command.WorkerUnitId,
                    out var pointer))
            {
                command.OwnsCommandMode = false;
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (unit.r_AliveState != AliveState.IsAlive
                || unchecked((int)unit.r_GlobalId) != command.WorkerGlobalId
                || unit.r_ControllableForPlayerId != command.WorkerOwner
                || unit.r_UnitChimp != command.WorkerType)
            {
                // Nur die IDENTITAET entscheidet hier. Frueher stand hier
                // zusaetzlich die Arbeitsbindung - mit der Folge, dass einem
                // Arbeiter, dessen Werkstatt abgebrannt war, der Befehlsmodus
                // NIE zurueckgegeben wurde. Er blieb dauerhaft im
                // Befehlszweig der Engine haengen und nahm nie wieder Arbeit
                // auf. Der geschriebene Wert stammt aus genau dieser Einheit;
                // dass ihr Arbeitsplatz weg ist, aendert daran nichts.
                command.OwnsCommandMode = false;
                _warning(
                    "Worker militia refused command-mode rollback after the "
                    + "worker identity changed; native fields were not "
                    + "touched.");
                return;
            }
            NativeSelectionLease selection = _selectionLease;
            if (selection != null
                && selection.UnitId == command.WorkerUnitId
                && SelectionLeaseIdentityMatches(selection, ref unit)
                && !selection.TemporarilySuppressed
                && SeInteropFieldAliases.CommandMode(ref unit) == 1)
            {
                // The selection lease will restore the shared flag after the
                // native deselection. Do not pull it out from under that path.
                return;
            }
            if (SeInteropFieldAliases.CommandMode(ref unit) != command.OriginalCommandModeValue)
            {
                if (SeInteropFieldAliases.CommandMode(ref unit) != 1)
                {
                    command.OwnsCommandMode = false;
                    _warning(
                        "Worker militia lost command-mode ownership during "
                        + reason + "; the foreign value was preserved.");
                    return;
                }
                SeInteropFieldAliases.CommandMode(ref unit) = command.OriginalCommandModeValue;
            }
            if (SeInteropFieldAliases.CommandMode(ref unit) != command.OriginalCommandModeValue)
            {
                // The write did not hold. Ownership is dropped either way, so
                // this feature stops writing to that unit; the engine keeps
                // whatever it has. Throwing here would stop the militia on a
                // path that every mission end and every rollback reaches.
                if (_evidenceLogged.Add("command_mode_rollback_failed"))
                {
                    _warning(
                        "Worker militia could not restore a command mode during "
                        + reason + " (live="
                        + SeInteropFieldAliases.CommandMode(ref unit).ToString(CultureInfo.InvariantCulture)
                        + " expected="
                        + command.OriginalCommandModeValue.ToString(
                            CultureInfo.InvariantCulture)
                        + "); ownership is dropped and nothing further is "
                        + "written to that unit.");
                }
                command.OwnsCommandMode = false;
                return;
            }
            command.OwnsCommandMode = false;
            string unitName = UnitName(command.WorkerType);
            if (_evidenceLogged.Add("native_state_restored." + unitName))
            {
                _info(RuntimeLogContract.WorkerMilitiaNativeStateRestoredEvidence(
                    unitName));
            }
        }

        private static void BeginFight(
            CommandState command,
            UnitSnapshot worker,
            UnitSnapshot target,
            bool explicitTarget,
            int now)
        {
            if (command == null
                || !CanEnterMilitiaCombat(command.WorkerType))
            {
                return;
            }
            command.TargetUnitId = target.Id;
            command.TargetGlobalId = target.GlobalId;
            command.ExplicitTarget = explicitTarget;
            command.Phase = MissionPhase.Fighting;
            // The leash remains at the command's current contact/guard anchor.
            // StartOrRetarget anchors autonomous acquisition at the worker;
            // outbound interception moves it to that contact point; a manual
            // explicit target is intentionally un-leashed. A later target may
            // not drag an already established local anchor along.
            command.NextMoveTick = now;
            command.NextAttackTick = now;
            command.HoldDeadlineTick = 0;
            if (explicitTarget)
            {
                command.ResumeHoldAfterCombat = false;
                command.PausedHoldRemainingMilliseconds = 0;
            }
            ResetMovementStall(command, now);
        }

        private void RetargetOrResume(
            CommandState command,
            UnitSnapshot worker,
            UnitSpatialIndex spatialIndex,
            int now,
            int excludedTarget)
        {
            bool mayChainTarget = CanEnterMilitiaCombat(command.WorkerType)
                && WorkerMilitiaMissionRules.MayChainAutomaticTarget(
                    command.Manual,
                    command.ExplicitTarget);
            UnitSnapshot replacement = mayChainTarget
                ? FindBestEnemy(
                    worker,
                    spatialIndex,
                    GuardRadius(command.WorkerType),
                    command,
                    excludedTarget)
                : null;
            if (replacement != null)
            {
                command.TargetUnitId = replacement.Id;
                command.TargetGlobalId = replacement.GlobalId;
                command.ExplicitTarget = false;
                command.Phase = MissionPhase.Fighting;
                command.NextMoveTick = now;
                command.NextAttackTick = now;
                return;
            }
            if (command.ResumeHoldAfterCombat)
            {
                command.TargetUnitId = 0;
                command.TargetGlobalId = 0;
                command.ExplicitTarget = false;
                command.Phase = MissionPhase.Holding;
                command.HoldDeadlineTick = unchecked(
                    now + command.PausedHoldRemainingMilliseconds);
                command.ResumeHoldAfterCombat = false;
                command.PausedHoldRemainingMilliseconds = 0;
                return;
            }
            if (command.HasManualDestination
                && !command.ManualDestinationReached)
            {
                command.TargetUnitId = 0;
                command.TargetGlobalId = 0;
                command.ExplicitTarget = false;
                command.Phase = MissionPhase.Outbound;
                command.NextMoveTick = now;
                _info(
                    "Worker militia " + UnitName(command.WorkerType)
                    + " resumes its interrupted manual destination.");
                return;
            }
            CompleteDirectWork(
                command,
                worker,
                "combat_clear",
                true);
        }

        private void BeginHolding(CommandState command, int now)
        {
            command.TargetUnitId = 0;
            command.TargetGlobalId = 0;
            command.ExplicitTarget = false;
            command.ManualDestinationReached = true;
            command.Phase = MissionPhase.Holding;
            command.ResumeHoldAfterCombat = false;
            command.PausedHoldRemainingMilliseconds = 0;
            command.HoldDeadlineTick = unchecked(
                now + GeneratedWorkerMilitiaContract.HoldDurationMilliseconds);
            string unit = UnitName(command.WorkerType);
            if (_evidenceLogged.Add("hold_started." + unit))
            {
                _info(RuntimeLogContract.WorkerMilitiaHoldStartedEvidence(
                    unit,
                    GeneratedWorkerMilitiaContract.HoldDurationMilliseconds));
            }
            _info(
                "Worker militia " + unit + " holds its manual destination for "
                + GeneratedWorkerMilitiaContract.HoldDurationMilliseconds.ToString(
                    CultureInfo.InvariantCulture)
                + " ms while its guard radius remains clear.");
        }

        /// <summary>
        /// Gives up one mission whose worker no longer matches the provenance
        /// captured when it started, without writing to the native unit and
        /// without stopping the feature.
        /// </summary>
        /// <remarks>
        /// Names which of the three provenance parts changed, because the right
        /// long-term answer differs per part and cannot be decided without that
        /// number. A destroyed workplace only moves the work link, and for that
        /// case the worker's identity is still intact - restoring its command
        /// mode would be both safe and desirable. Occupancy or tribe drift can
        /// mean a reused slot, where touching anything is wrong. Until a real
        /// run says which one actually occurs, all three take the careful path.
        /// </remarks>
        private void AbandonCommandAfterProvenanceChange(
            CommandState command,
            string reason)
        {
            if (command == null)
            {
                return;
            }
            int unitId = command.WorkerUnitId;
            // Telemetry only, and it must never be the thing that throws. The
            // worker may be gone by now: LuaUnitAPI.GetUnitField returns null
            // for a missing unit and ReadExposedUnitInt turns that into an
            // exception, which would put the session-killer straight back in.
            string workLinkChanged = "unknown";
            string tribeChanged = "unknown";
            string occupancyChanged = "unknown";
            bool workerAlive = GameUnitManagerAPI.Instance != null
                && IsPlausibleUnitId(unitId)
                && GameUnitManagerAPI.Instance.IsValid(unitId);
            if (workerAlive)
            {
                try
                {
                    workLinkChanged = TelemetryBoolean(
                        ReadExposedUnitInt(
                            unitId,
                            "r_LinkedProductionBuildingId")
                            != command.OriginalWorkLink);
                    tribeChanged = TelemetryBoolean(
                        !TribeProvenanceMatches(
                            unitId,
                            command.OriginalTribeId,
                            out _));
                    occupancyChanged = TelemetryBoolean(
                        !WorkerOccupancyMatches(
                            unitId,
                            command.WorkerGlobalId,
                            command.WorkerOwner,
                            command.WorkerType,
                            command.Occupancy));
                }
                catch (Exception)
                {
                    // Keep whatever was resolved; the mission is given up
                    // either way.
                }
            }
            RestoreOwnedCommandMode(command, "provenance change during " + reason);
            command.OwnsCommandMode = false;
            command.DirectWorkCompletionPending = false;
            _commands.Remove(unitId);
            _pendingDirectWorkCompletions.Remove(unitId);
            _pendingWorkResumptionProofs.Remove(unitId);
            _warning(
                "Worker militia gave up a mission because the worker's "
                + "provenance changed while it ran (reason=" + reason
                + " unit_id=" + unitId.ToString(CultureInfo.InvariantCulture)
                + " worker_alive=" + TelemetryBoolean(workerAlive)
                + " work_link_changed=" + workLinkChanged
                + " tribe_changed=" + tribeChanged
                + " occupancy_changed=" + occupancyChanged
                + "). Nothing native was written and the feature stays up; "
                + "before 2026-08-27 this stopped the militia for the rest of "
                + "the session.");
        }

        private void CompleteDirectWork(
            CommandState command,
            UnitSnapshot worker,
            string reason,
            bool combatCompleted,
            bool emitRuntimeEvidence = true)
        {
            if (command == null || worker == null)
            {
                // Aufrufer aus dem Takt und von der nativen Grenze; ein Wurf
                // hier nimmt den ganzen Mod mit.
                if (_evidenceLogged.Add("direct_work_handoff_without_command"))
                {
                    _warning(
                        "Worker militia direct-work handoff was called without "
                        + "a command or worker; the handoff is skipped.");
                }
                return;
            }
            NoteWorkplaceLoss(command);
            if (worker.Id != command.WorkerUnitId
                || worker.GlobalId != command.WorkerGlobalId
                || worker.Type != command.WorkerType
                || worker.Owner != command.WorkerOwner)
            {
                // This used to throw, and the throw left Tick() uncaught: the
                // host then tore the whole feature down for the rest of the
                // session (ExtensionFeatureHost "tick" -> FailAndRollback).
                //
                // The condition is not a contract violation, it is an ordinary
                // game event. The mission ends at "combat_clear" while the
                // worker's own workplace has meanwhile burned down, been
                // demolished or been re-staffed - during a fight, which is the
                // one situation this feature exists for. Killing the militia
                // because a hunter's hut was destroyed while its hunter
                // defended it is exactly the failure mode the melee/arrow fix
                // of 2026-08-19 removed elsewhere and missed here.
                //
                // The safety property is unchanged: nothing is written to a
                // unit whose provenance no longer matches. The command is
                // simply given up.
                AbandonCommandAfterProvenanceChange(command, reason);
                return;
            }
            PendingDirectWorkCompletion existing;
            if (_pendingDirectWorkCompletions.TryGetValue(
                    command.WorkerUnitId,
                    out existing))
            {
                if (ReferenceEquals(existing.Command, command)
                    && existing.WorkerGlobalId == command.WorkerGlobalId
                    && existing.WorkerOwner == command.WorkerOwner
                    && existing.WorkerType == command.WorkerType)
                {
                    return;
                }
                // Ein fremder Eintrag haelt den Platz. Der bestehende
                // Eigentuemer wird nicht angetastet, und dieser Uebergang
                // entfaellt - der Mod laeuft weiter.
                if (_evidenceLogged.Add("direct_work_slot_owned"))
                {
                    _warning(
                        "Worker militia found its direct-work completion slot "
                        + "already owned for unit_id="
                        + command.WorkerUnitId.ToString(
                            CultureInfo.InvariantCulture)
                        + "; the existing owner is left alone and this handoff "
                        + "is skipped.");
                }
                return;
            }
            MissionPhase snapshotPhase = command.Phase;
            int snapshotTargetGlobalId = command.TargetGlobalId;
            if (snapshotPhase == MissionPhase.Fighting
                && (snapshotTargetGlobalId <= 0
                    || snapshotTargetGlobalId == command.WorkerGlobalId))
            {
                // A Fighting snapshot needs a non-worker target identity so
                // Load v4 can re-enter the ordinary invalid-target scan and
                // reach the same direct-work boundary. The sentinel is never
                // resolved as a live target during restore.
                snapshotTargetGlobalId = UnresolvedSavedTargetGlobalId;
            }
            int snapshotHoldRemainingMilliseconds = snapshotPhase
                    == MissionPhase.Holding
                ? RemainingMilliseconds(
                    SimulationNowMilliseconds(),
                    command.HoldDeadlineTick,
                    GeneratedWorkerMilitiaContract.HoldDurationMilliseconds)
                : 0;
            command.DirectWorkSnapshotPhase = snapshotPhase;
            command.DirectWorkSnapshotTargetGlobalId = snapshotTargetGlobalId;
            command.DirectWorkSnapshotExplicitTarget = command.ExplicitTarget;
            command.DirectWorkSnapshotHoldRemainingMilliseconds =
                snapshotHoldRemainingMilliseconds;
            command.TargetUnitId = 0;
            command.TargetGlobalId = 0;
            command.ExplicitTarget = false;
            command.HoldDeadlineTick = 0;
            command.Phase = MissionPhase.DirectWorkPending;
            command.DirectWorkCompletionPending = true;
            _pendingDirectWorkCompletions.Add(
                command.WorkerUnitId,
                new PendingDirectWorkCompletion
                {
                    Command = command,
                    WorkerUnitId = command.WorkerUnitId,
                    WorkerGlobalId = command.WorkerGlobalId,
                    WorkerOwner = command.WorkerOwner,
                    WorkerType = command.WorkerType,
                    OriginalWorkLink = command.OriginalWorkLink,
                    OriginalTribeId = command.OriginalTribeId,
                    Reason = reason,
                    CombatCompleted = combatCompleted,
                    EmitRuntimeEvidence = emitRuntimeEvidence,
                    Homeless = command.Homeless,
                    Occupancy = CopyOccupancy(command.Occupancy),
                    SnapshotPhase = snapshotPhase,
                    SnapshotTargetGlobalId = snapshotTargetGlobalId,
                    SnapshotExplicitTarget =
                        command.DirectWorkSnapshotExplicitTarget,
                    SnapshotHoldRemainingMilliseconds =
                        snapshotHoldRemainingMilliseconds,
                });
            _info(
                "Worker militia queued an identity-bound direct-work handoff "
                + "for the next EngineInterface.run postfix: unit_id="
                + command.WorkerUnitId.ToString(CultureInfo.InvariantCulture)
                + " reason=" + reason + ".");
        }

        private void CompletePendingDirectWorkAtNativeBoundary()
        {
            if (!_insideNativeRunPostfix
                || _nativeRunThreadId <= 0
                || Thread.CurrentThread.ManagedThreadId != _nativeRunThreadId)
            {
                // Der Aufrufer hat die Grenze bereits geprueft; das hier ist
                // die zweite Sicherung. Sie darf melden und aussetzen, aber
                // nicht durch nativen Code hindurch werfen.
                if (_evidenceLogged.Add("direct_work_boundary_escaped"))
                {
                    _warning(
                        "Worker militia direct-work completion was reached "
                        + "outside the native EngineInterface.run postfix; the "
                        + "queued completions wait for the next boundary.");
                }
                return;
            }
            var pendingCompletions =
                new List<PendingDirectWorkCompletion>(
                    _pendingDirectWorkCompletions.Values);
            foreach (PendingDirectWorkCompletion pending in pendingCompletions)
            {
                CommandState command = null;
                bool commandMatches = pending != null
                    && _commands.TryGetValue(
                        pending.WorkerUnitId,
                        out command)
                    && PendingDirectWorkMatchesCommand(pending, command);
                if (!commandMatches)
                {
                    if (pending != null)
                    {
                        _pendingDirectWorkCompletions.Remove(
                            pending.WorkerUnitId);
                    }
                    _warning(
                        "Worker militia discarded a stale direct-work boundary "
                        + "request without touching native state.");
                    continue;
                }
                NoteWorkplaceLoss(command);
                if (!CommandIdentityMatchesLiveWorker(
                        command,
                        command.WorkerUnitId)
                    || !CommandMatchesLiveWorkerProvenance(
                        command,
                        command.WorkerUnitId))
                {
                    _pendingDirectWorkCompletions.Remove(
                        command.WorkerUnitId);
                    _commands.Remove(command.WorkerUnitId);
                    command.DirectWorkCompletionPending = false;
                    command.OwnsCommandMode = false;
                    if (_selectedWorkerId == command.WorkerUnitId)
                    {
                        _selectedWorkerId = 0;
                    }
                    _warning(
                        "Worker militia discarded a direct-work completion after "
                        + "unit identity or provenance changed; no native field "
                        + "was restored through the stale slot.");
                    continue;
                }
                CompletePendingDirectWorkAtNativeBoundary(pending, command);
            }
        }

        private static bool PendingDirectWorkMatchesCommand(
            PendingDirectWorkCompletion pending,
            CommandState command)
        {
            return pending != null
                && command != null
                && pending.Command != null
                && ReferenceEquals(command, pending.Command)
                && command.DirectWorkCompletionPending
                && command.Phase == MissionPhase.DirectWorkPending
                && command.WorkerUnitId == pending.WorkerUnitId
                && command.WorkerGlobalId == pending.WorkerGlobalId
                && command.WorkerOwner == pending.WorkerOwner
                && command.WorkerType == pending.WorkerType
                && command.OriginalWorkLink == pending.OriginalWorkLink
                && command.OriginalTribeId == pending.OriginalTribeId
                && command.Homeless == pending.Homeless
                && (command.Homeless
                    ? command.Occupancy == null && pending.Occupancy == null
                    : OccupancyProvenanceMatches(
                        command.Occupancy,
                        pending.Occupancy))
                && command.DirectWorkSnapshotPhase == pending.SnapshotPhase
                && command.DirectWorkSnapshotTargetGlobalId
                    == pending.SnapshotTargetGlobalId
                && command.DirectWorkSnapshotExplicitTarget
                    == pending.SnapshotExplicitTarget
                && command.DirectWorkSnapshotHoldRemainingMilliseconds
                    == pending.SnapshotHoldRemainingMilliseconds;
        }

        private void CompletePendingDirectWorkAtNativeBoundary(
            PendingDirectWorkCompletion pending,
            CommandState command)
        {
            NativeSelectionLease selection = _selectionLease;
            bool stillSelected = _selectedWorkerId == command.WorkerUnitId
                || (selection != null
                    && selection.UnitId == command.WorkerUnitId
                    && selection.GlobalId == command.WorkerGlobalId
                    && selection.Owner == command.WorkerOwner
                    && selection.Type == command.WorkerType);
            if (!stillSelected)
            {
                RestoreOwnedCommandMode(command, "direct work handoff");
            }
            if (stillSelected)
            {
                _selectedWorkerId = 0;
                DeselectOwnedMilitia("direct work handoff");
                ReleaseNativeSelection("direct work handoff", false);
            }
            UnitSnapshot resumedWorker = CaptureUnit(command.WorkerUnitId);
            bool commandModeRestored = false;
            ushort liveCommandMode = ushort.MaxValue;
            if (resumedWorker != null
                && GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    command.WorkerUnitId,
                    out var resumedPointer))
            {
                ref GameUnit resumedUnit = ref resumedPointer.AsRef();
                liveCommandMode = SeInteropFieldAliases.CommandMode(ref resumedUnit);
                commandModeRestored = liveCommandMode
                    == command.OriginalCommandModeValue;
            }
            // Ein waehrend des Einsatzes verschwundener Arbeitsplatz kann am
            // Ende nicht mehr erhalten sein - das zu verlangen hiesse, jeden
            // solchen Einsatz als Fehlschlag zu melden. Erhalten sein MUSS,
            // was dieses Merkmal selbst angefasst hat: der Befehlsmodus.
            bool workLinkPreserved = command.Homeless
                || command.WorkplaceLost
                || (resumedWorker != null
                    && resumedWorker.GlobalId == command.WorkerGlobalId
                    && resumedWorker.WorkLink == command.OriginalWorkLink);
            bool tribePreserved = resumedWorker != null
                && resumedWorker.GlobalId == command.WorkerGlobalId
                && TribeProvenanceMatches(
                    command.WorkerUnitId,
                    command.OriginalTribeId,
                    out _);
            bool occupancyPreserved = command.Homeless
                || command.WorkplaceLost
                || WorkerOccupancyMatches(
                    command.WorkerUnitId,
                    command.WorkerGlobalId,
                    command.WorkerOwner,
                    command.WorkerType,
                    command.Occupancy);
            if (!commandModeRestored
                || !workLinkPreserved
                || !tribePreserved
                || !occupancyPreserved)
            {
                // This sits at the end of EVERY mission, on the run-postfix
                // path. Throwing here stopped the feature for the session, and
                // it did so at the very moment the worker was being handed
                // back - the most ordinary moment there is. None of the four
                // read-backs is under this feature's control any more at this
                // point: the workshop can have burned down between the
                // pre-check and here, and the command mode is restored through
                // the selection release when the worker was still selected.
                //
                // Stopping cannot repair any of that; it only guarantees that
                // nothing else works either. The command is dropped so this
                // feature stops touching the unit, and the four flags are named
                // so the cause is decidable from one log.
                _warning(
                    "Worker militia could not verify its work handoff and let "
                    + "the worker go: unit_id="
                    + command.WorkerUnitId.ToString(CultureInfo.InvariantCulture)
                    + " command_mode_restored="
                    + TelemetryBoolean(commandModeRestored)
                    + " live_command_mode="
                    + liveCommandMode.ToString(CultureInfo.InvariantCulture)
                    + " expected_command_mode="
                    + command.OriginalCommandModeValue.ToString(
                        CultureInfo.InvariantCulture)
                    + " work_link_preserved="
                    + TelemetryBoolean(workLinkPreserved)
                    + " tribe_preserved=" + TelemetryBoolean(tribePreserved)
                    + " occupancy_preserved="
                    + TelemetryBoolean(occupancyPreserved)
                    + " workplace_lost=" + TelemetryBoolean(command.WorkplaceLost)
                    + ". The mission is over either way; the feature keeps "
                    + "running.");
                command.OwnsCommandMode = false;
                command.DirectWorkCompletionPending = false;
                _commands.Remove(command.WorkerUnitId);
                _pendingDirectWorkCompletions.Remove(command.WorkerUnitId);
                _pendingWorkResumptionProofs.Remove(command.WorkerUnitId);
                return;
            }
            command.OwnsCommandMode = false;
            command.DirectWorkCompletionPending = false;
            if (!_commands.TryGetValue(command.WorkerUnitId, out var ownedCommand)
                || !ReferenceEquals(ownedCommand, command))
            {
                // Der Befehl wurde zwischen Einreihung und Grenze ersetzt oder
                // entfernt - etwa weil der Arbeiter gestorben ist. Nur die
                // eigene Buchhaltung wird aufgeraeumt.
                if (_evidenceLogged.Add("direct_work_owner_changed"))
                {
                    _warning(
                        "Worker militia direct-work command ownership changed "
                        + "before the native boundary could finalize it; only "
                        + "this mission's bookkeeping is dropped.");
                }
                _pendingDirectWorkCompletions.Remove(command.WorkerUnitId);
                _pendingWorkResumptionProofs.Remove(command.WorkerUnitId);
                return;
            }
            _commands.Remove(command.WorkerUnitId);
            _pendingDirectWorkCompletions.Remove(command.WorkerUnitId);
            string unit = UnitName(command.WorkerType);
            string mode = command.Manual ? "manual" : "autonomous";
            bool observedCombat = pending.CombatCompleted
                && command.DamageObserved;
            if (pending.EmitRuntimeEvidence
                && observedCombat
                && _evidenceLogged.Add(
                    "combat_to_direct_work." + unit + "." + mode))
            {
                _info(RuntimeLogContract.WorkerMilitiaCombatDirectWorkEvidence(
                    unit,
                    mode));
            }
            bool monitorWorkResumption = pending.EmitRuntimeEvidence
                && !command.Homeless
                && !command.WorkplaceLost
                && (!pending.CombatCompleted || observedCombat);
            if (monitorWorkResumption)
            {
                if (_evidenceLogged.Add(
                        "handoff_restored." + unit + "." + mode + "."
                        + pending.Reason))
                {
                    _info(RuntimeLogContract.WorkerMilitiaHandoffRestoredEvidence(
                        unit,
                        mode,
                        pending.Reason,
                        liveCommandMode,
                        command.OriginalCommandModeValue,
                        resumedWorker.WorkLink,
                        command.OriginalWorkLink,
                        resumedWorker.TribeId,
                        command.OriginalTribeId));
                }
                _pendingWorkResumptionProofs[command.WorkerUnitId] =
                    new PendingWorkResumptionProof
                    {
                        WorkerUnitId = command.WorkerUnitId,
                        WorkerGlobalId = command.WorkerGlobalId,
                        WorkerOwner = command.WorkerOwner,
                        WorkerType = command.WorkerType,
                        OriginalWorkLink = command.OriginalWorkLink,
                        OriginalTribeId = command.OriginalTribeId,
                        Reason = pending.Reason,
                        Mode = mode,
                        DeadlineTick = unchecked(
                            SimulationNowMilliseconds()
                            + WorkResumptionProofTimeoutMilliseconds),
                        Occupancy = CopyOccupancy(command.Occupancy),
                    };
                _info(
                    "Worker militia restored a direct-work handoff and now awaits "
                    + "later native worker activity: unit="
                    + unit + " reason=" + pending.Reason
                    + " return_move=false boundary=EngineInterface.run_postfix.");
            }
        }

        private void CompleteWorkResumptionProofFromNativeMove(int unitId)
        {
            PendingWorkResumptionProof proof;
            if (_commands.ContainsKey(unitId)
                || !_pendingWorkResumptionProofs.TryGetValue(
                    unitId,
                    out proof))
            {
                return;
            }
            bool exactWorker = WorkerOccupancyMatches(
                    unitId,
                    proof.WorkerGlobalId,
                    proof.WorkerOwner,
                    proof.WorkerType,
                    proof.Occupancy)
                && ReadExposedUnitInt(
                    unitId,
                    "r_LinkedProductionBuildingId")
                    == proof.OriginalWorkLink
                && TribeProvenanceMatches(
                    unitId,
                    proof.OriginalTribeId,
                    out _);
            _pendingWorkResumptionProofs.Remove(unitId);
            if (!exactWorker)
            {
                _warning(
                    "Worker militia discarded a delayed work-resumption proof "
                    + "after identity or occupancy changed; no native field "
                    + "was restored.");
                return;
            }
            string unit = UnitName(proof.WorkerType);
            string evidenceKey = "direct_work_resumed." + unit + "."
                + proof.Mode + "." + proof.Reason;
            if (_evidenceLogged.Add(evidenceKey))
            {
                _info(
                    RuntimeLogContract.WorkerMilitiaDirectWorkResumedEvidence(
                        unit,
                        proof.Mode,
                        proof.Reason,
                        "native_worker_move"));
            }
            _info(
                "Worker militia observed later native worker movement after "
                + "the direct-work handoff: unit=" + unit + ".");
        }

        private void ExpireWorkResumptionProofs(int now)
        {
            if (_pendingWorkResumptionProofs.Count == 0)
            {
                return;
            }
            var expired = new List<int>();
            foreach (KeyValuePair<int, PendingWorkResumptionProof> item in
                _pendingWorkResumptionProofs)
            {
                if (HasReached(now, item.Value.DeadlineTick))
                {
                    expired.Add(item.Key);
                }
            }
            foreach (int unitId in expired)
            {
                PendingWorkResumptionProof proof =
                    _pendingWorkResumptionProofs[unitId];
                _pendingWorkResumptionProofs.Remove(unitId);
                _warning(
                    "Worker militia work handoff remained unproved after "
                    + WorkResumptionProofTimeoutMilliseconds.ToString(
                        CultureInfo.InvariantCulture)
                    + " ms: unit=" + UnitName(proof.WorkerType)
                    + " reason=" + proof.Reason + ".");
            }
        }

        private void FireHunterArrow(
            CommandState command,
            UnitSnapshot worker,
            UnitSnapshot target,
            int now)
        {
            if (command == null
                || command.WorkerType != eChimps.CHIMP_TYPE_HUNTER
                || !CanEnterMilitiaCombat(command.WorkerType))
            {
                return;
            }
            if (!CommandMatchesLiveWorkerProvenance(
                    command,
                    command.WorkerUnitId))
            {
                // Not a contract violation but an ordinary game event:
                // the worker's own workplace can burn down, be demolished
                // or be re-staffed while it fights, and the engine can
                // take its command mode back. Throwing here left Tick()
                // uncaught and the host tore the feature down for the
                // whole session. Nothing is acted on either way; the
                // mission is given up instead of the mod.
                AbandonCommandAfterProvenanceChange(command, "hunter arrow");
                return;
            }
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            int archerDamage = units.GetRangedArrowDamageTo(target.Type);
            command.NextAttackTick = unchecked(
                now + GeneratedWorkerMilitiaContract.HunterAttackCooldownMilliseconds);
            if (archerDamage <= 0)
            {
                return;
            }
            var sourceWorld = units.GetCurrentWorldTilePosition(worker.Id);
            var targetWorld = units.GetCurrentWorldTilePosition(target.Id);
            int sourceElevation;
            int targetElevation;
            if (!TryReadExposedUnitInt(
                    worker.Id,
                    "r_HeightElevation",
                    out sourceElevation)
                || !TryReadExposedUnitInt(
                    target.Id,
                    "r_HeightElevation",
                    out targetElevation))
            {
                // The target died between the scan and the shot - the ordinary
                // case in a fight. Skip this one arrow, exactly as a refused
                // projectile is skipped.
                if (_evidenceLogged.Add("arrow_target_gone"))
                {
                    _info(
                        "Worker militia skipped a hunter arrow because its "
                        + "target was gone at the moment of the shot. Only the "
                        + "shot is skipped.");
                }
                return;
            }
            ExpireOwnedProjectiles(now);
            if (_ownedProjectiles.Count >= MaxOwnedProjectiles)
            {
                if (_evidenceLogged.Add("arrow_ledger_full"))
                {
                    _warning(
                        "Worker militia skipped a hunter arrow because its "
                        + "bounded projectile ledger is full. No untracked "
                        + "full-damage arrow was created.");
                }
                return;
            }
            long projectileId = GameProjectileManagerAPI.Instance.CreateProjectile(
                worker.Id,
                worker.Owner,
                sourceWorld.X,
                sourceWorld.Y,
                sourceElevation,
                targetWorld.X,
                targetWorld.Y,
                targetElevation,
                ProjectileType.ArcherArrow,
                target.Id);
            if (projectileId <= 0)
            {
                // Same class of transient failure as the melee strike above:
                // the projectile manager refuses when the target or the firing
                // position stops being valid. Skip this shot, keep the militia.
                if (_evidenceLogged.Add("arrow_refused"))
                {
                    _warning(
                        "Worker militia hunter arrow was refused by the native"
                        + " projectile manager and was skipped: worker_id="
                        + command.WorkerUnitId.ToString(
                            CultureInfo.InvariantCulture)
                        + " target_id="
                        + target.Id.ToString(CultureInfo.InvariantCulture)
                        + ". The militia keeps running.");
                }
            }
            else
            {
                RegisterOwnedProjectile(
                    projectileId,
                    command,
                    target,
                    archerDamage,
                    now);
            }
        }

        private void RegisterOwnedProjectile(
            long projectileId,
            CommandState command,
            UnitSnapshot target,
            int referenceDamage,
            int now)
        {
            if (projectileId <= 0
                || command == null
                || target == null)
            {
                _warning(
                    "Worker militia could not register a returned projectile "
                    + "identity; that shot is not allowed to become a full "
                    + "damage fallback.");
                return;
            }
            int id = unchecked((int)projectileId);
            _ownedProjectiles[id] = new OwnedProjectile
            {
                ProjectileId = id,
                MilitiaGeneration = command.Generation,
                WorkerUnitId = command.WorkerUnitId,
                WorkerGlobalId = command.WorkerGlobalId,
                WorkerOwner = command.WorkerOwner,
                WorkerType = command.WorkerType,
                TargetUnitId = target.Id,
                TargetGlobalId = target.GlobalId,
                ReferenceDamage = referenceDamage,
                DeadlineTick = unchecked(
                    now + OwnedProjectileLifetimeMilliseconds),
            };
        }

        private void ExpireOwnedProjectiles(int now)
        {
            if (_ownedProjectiles.Count == 0)
            {
                return;
            }
            var expired = new List<int>();
            foreach (OwnedProjectile projectile in _ownedProjectiles.Values)
            {
                if (HasReached(now, projectile.DeadlineTick))
                {
                    expired.Add(projectile.ProjectileId);
                }
            }
            foreach (int projectileId in expired)
            {
                _ownedProjectiles.Remove(projectileId);
            }
        }

        private void StrikeWithWoodcutter(
            CommandState command,
            UnitSnapshot target,
            int now)
        {
            if (!CommandMatchesLiveWorkerProvenance(
                    command,
                    command == null ? 0 : command.WorkerUnitId))
            {
                // Not a contract violation but an ordinary game event:
                // the worker's own workplace can burn down, be demolished
                // or be re-staffed while it fights, and the engine can
                // take its command mode back. Throwing here left Tick()
                // uncaught and the host tore the feature down for the
                // whole session. Nothing is acted on either way; the
                // mission is given up instead of the mod.
                AbandonCommandAfterProvenanceChange(
                    command,
                    "woodcutter strike");
                return;
            }
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            int damage = units.GetMeleeDamageFromTo(
                eChimps.CHIMP_TYPE_WOODCUTTER,
                target.Type);
            command.NextAttackTick = unchecked(
                now + GeneratedWorkerMilitiaContract.WoodcutterAttackCooldownMilliseconds);
            if (damage <= 0)
            {
                return;
            }
            if (!units.DamageUnitMelee(command.WorkerUnitId, target.Id, damage))
            {
                // A refused strike is transient: the target can die, move out
                // of reach or become invalid between the scan and the blow.
                // Only this one attack is skipped - the cooldown above already
                // applies. Tearing the whole feature down over it took the
                // militia offline mid-session on 2026-08-19 and left the
                // workers unselectable for the rest of the game.
                if (_evidenceLogged.Add("melee_refused"))
                {
                    _warning(
                        "Worker militia woodcutter melee strike was refused by"
                        + " the native entry point and was skipped: worker_id="
                        + command.WorkerUnitId.ToString(
                            CultureInfo.InvariantCulture)
                        + " target_id="
                        + target.Id.ToString(CultureInfo.InvariantCulture)
                        + " damage="
                        + damage.ToString(CultureInfo.InvariantCulture)
                        + ". The militia keeps running.");
                }
            }
        }

        private bool MoveWorker(
            CommandState command,
            int tileX,
            int tileY,
            int now,
            string phase)
        {
            if (!CommandMatchesLiveWorkerProvenance(
                    command,
                    command == null ? 0 : command.WorkerUnitId))
            {
                // Not a contract violation but an ordinary game event:
                // the worker's own workplace can burn down, be demolished
                // or be re-staffed while it fights, and the engine can
                // take its command mode back. Throwing here left Tick()
                // uncaught and the host tore the feature down for the
                // whole session. Nothing is acted on either way; the
                // mission is given up instead of the mod.
                AbandonCommandAfterProvenanceChange(
                    command,
                    "worker move (" + phase + ")");
                return false;
            }
            int safeTileX = ClampMapTile(tileX);
            int safeTileY = ClampMapTile(tileY);
            bool destinationChanged = !command.HasIssuedMove
                || command.IssuedMoveX != safeTileX
                || command.IssuedMoveY != safeTileY;
            if (_internalMoveDepth != 0)
            {
                if (_evidenceLogged.Add("nested_internal_move_refused"))
                {
                    _warning(
                        "Worker militia refused a nested internal move; the "
                        + "existing synchronous return-value owner was left "
                        + "untouched.");
                }
                return false;
            }

            _internalMoveUnitId = command.WorkerUnitId;
            _internalMoveTileX = safeTileX;
            _internalMoveTileY = safeTileY;
            _internalMovePostObserved = false;
            _internalMoveReturnValue = 0;
            bool callCompleted = false;
            Exception callFailure = null;
            _internalMoveDepth++;
            try
            {
                GameUnitManagerAPI.Instance.MoveToTile(
                    command.WorkerUnitId,
                    safeTileX,
                    safeTileY);
                callCompleted = true;
            }
            catch (Exception exception)
            {
                callFailure = exception;
            }
            finally
            {
                _internalMoveDepth--;
            }
            bool postObserved = _internalMovePostObserved;
            long nativeReturnValue = _internalMoveReturnValue;
            _internalMoveUnitId = 0;
            _internalMoveTileX = 0;
            _internalMoveTileY = 0;
            _internalMovePostObserved = false;
            _internalMoveReturnValue = 0;

            if (!callCompleted || callFailure != null)
            {
                command.NextMoveTick = unchecked(
                    now
                    + GeneratedWorkerMilitiaContract.MoveRefreshMilliseconds);
                if (_evidenceLogged.Add("move_call_failed." + phase))
                {
                    _warning(
                        "Worker militia move call failed for " + phase + ": "
                        + (callFailure == null
                            ? "native wrapper did not complete"
                            : callFailure.GetType().Name + ": "
                                + callFailure.Message)
                        + ". The mission remains retryable.");
                }
                return false;
            }
            if (!postObserved || nativeReturnValue <= 0)
            {
                command.NextMoveTick = unchecked(
                    now
                    + GeneratedWorkerMilitiaContract.MoveRefreshMilliseconds);
                string verdict = !postObserved
                    ? "post_callback_absent"
                    : "native_return="
                        + nativeReturnValue.ToString(CultureInfo.InvariantCulture);
                string refusalKey = "move_rejected."
                    + UnitName(command.WorkerType) + "." + phase;
                if (_evidenceLogged.Add(refusalKey))
                {
                    _warning(
                        "Worker militia did not publish a rejected move: unit="
                        + UnitName(command.WorkerType) + " phase=" + phase
                        + " " + verdict + ".");
                }
                return false;
            }
            if (!ApplyNativeMilitiaMoveState(command, phase))
            {
                command.NextMoveTick = unchecked(
                    now
                    + GeneratedWorkerMilitiaContract.MoveRefreshMilliseconds);
                return false;
            }
            if (destinationChanged)
            {
                ResetMovementStall(command, now);
            }
            command.NextMoveTick = unchecked(
                now + GeneratedWorkerMilitiaContract.MoveRefreshMilliseconds);
            command.HasIssuedMove = true;
            command.IssuedMoveX = safeTileX;
            command.IssuedMoveY = safeTileY;
            command.LastProgressTick = now;
            string key = "move." + UnitName(command.WorkerType) + "." + phase;
            if (_evidenceLogged.Add(key))
            {
                _info(
                    "Worker militia " + UnitName(command.WorkerType)
                    + " issued an accepted native move order for " + phase
                    + ": return="
                    + nativeReturnValue.ToString(CultureInfo.InvariantCulture)
                    + " state=0x65.");
            }
            return true;
        }

        /// <summary>
        /// Binds an accepted path to the move state the native tribe executor
        /// itself uses. This is a transient behavioral state, not a learned
        /// animation value.
        /// </summary>
        private bool ApplyNativeMilitiaMoveState(
            CommandState command,
            string source)
        {
            if (command == null
                || !_hunterMoveStateReady
                || _hunterMoveStateUnavailableForProcess
                || !_commands.TryGetValue(
                    command.WorkerUnitId,
                    out CommandState liveCommand)
                || !ReferenceEquals(liveCommand, command)
                || liveCommand.Generation != command.Generation
                || !CommandMatchesLiveWorkerProvenance(
                    command,
                    command.WorkerUnitId)
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    command.WorkerUnitId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (unit.r_AliveState != AliveState.IsAlive
                || unit.r_UnitChimp != command.WorkerType
                || unchecked((int)unit.r_GlobalId) != command.WorkerGlobalId
                || unit.r_ControllableForPlayerId != command.WorkerOwner
                || SeInteropFieldAliases.CommandMode(ref unit) != 1)
            {
                return false;
            }
            int previous = unit.r_AIState;
            if (previous != NativeMilitiaMoveState)
            {
                unit.r_AIState = NativeMilitiaMoveState;
            }
            if (unit.r_AIState != NativeMilitiaMoveState)
            {
                string key = "native_move_state_readback_failed."
                    + UnitName(command.WorkerType);
                if (_evidenceLogged.Add(key))
                {
                    _warning(
                        "Worker militia could not read back native move state "
                        + "0x65 for " + UnitName(command.WorkerType)
                        + " after " + source + ". The path is not published "
                        + "as a working militia move.");
                }
                return false;
            }
            string evidenceKey = "native_move_state."
                + UnitName(command.WorkerType);
            if (_evidenceLogged.Add(evidenceKey))
            {
                _info(
                    "Worker militia bound an accepted path to the engine's "
                    + "move state: unit=" + UnitName(command.WorkerType)
                    + " previous_ai="
                    + previous.ToString(CultureInfo.InvariantCulture)
                    + " ai=101(0x65) source=" + source + ".");
            }
            return true;
        }

        /// <summary>
        /// Decides whether the native move order actually has to be re-sent.
        /// </summary>
        /// <remarks>
        /// The engine restarts a unit's walk cycle whenever it receives a new
        /// move order (RVA 0x194FC0 re-syncs position/facing through RVA
        /// 0x199EE0 and rewrites the destination fields). The old 750-ms resend
        /// loop was therefore a concrete slide contributor, but no current
        /// game run has yet proved that removing it and adding state 0x65 fixes
        /// every visual cause. Only a changed destination - or a worker that
        /// has not advanced a single tile for <see cref="MoveStallMilliseconds"/>,
        /// which means the order was lost - now issues a new order.
        /// </remarks>
        private static bool ShouldIssueMove(
            CommandState command,
            UnitSnapshot worker,
            int tileX,
            int tileY,
            int now)
        {
            if (command == null || worker == null)
            {
                return false;
            }
            if (!command.HasIssuedMove
                || command.IssuedMoveX != ClampMapTile(tileX)
                || command.IssuedMoveY != ClampMapTile(tileY))
            {
                return true;
            }
            if (worker.X != command.LastProgressX
                || worker.Y != command.LastProgressY)
            {
                // The worker is walking; leave the running native order alone.
                command.LastProgressX = worker.X;
                command.LastProgressY = worker.Y;
                command.LastProgressTick = now;
                ResetMovementStall(command, now);
                return false;
            }
            return HasReached(
                now,
                unchecked(command.LastProgressTick + MoveStallMilliseconds));
        }

        private static void ResetMovementStall(CommandState command, int now)
        {
            if (command == null)
            {
                return;
            }
            command.StallWindowStartTick = now;
            command.StallRetryCount = 0;
        }

        private static bool ShouldAbortStalledManualMove(
            CommandState command,
            UnitSnapshot worker,
            int tileX,
            int tileY,
            int now)
        {
            if (command == null
                || worker == null
                || !command.Manual
                || !command.HasIssuedMove
                || command.IssuedMoveX != ClampMapTile(tileX)
                || command.IssuedMoveY != ClampMapTile(tileY))
            {
                return false;
            }
            command.StallRetryCount++;
            int elapsed = unchecked(now - command.StallWindowStartTick);
            return WorkerMilitiaMissionRules.ShouldAbortStalledManualMove(
                command.Manual,
                command.StallRetryCount,
                elapsed,
                ManualMoveAbortRetryFloor,
                ManualMoveAbortMilliseconds);
        }

        /// <summary>
        /// Bounded evidence for the walk animation: samples the animation
        /// fields of the commanded worker and, for comparison, of a worker of
        /// the same type that is doing its normal job in the very same tick.
        /// A commanded worker that walks correctly must show a changing
        /// sprite frame just like the reference worker does.
        /// </summary>
        private void LogMovementAnimationProbe(
            CommandState command,
            UnitSnapshot worker,
            List<UnitSnapshot> snapshots,
            string occasion)
        {
            if (command == null || worker == null)
            {
                return;
            }
            // Split the budget so a busy woodcutter can never consume every
            // probe and leave the hunter unmeasured, which is what the
            // 2026-08-19 run did.
            bool hunterProbe = worker.Type == eChimps.CHIMP_TYPE_HUNTER;
            int probeBudget = MaxAnimationProbes / 2;
            if (hunterProbe
                ? _hunterAnimationProbesLogged >= probeBudget
                : _animationProbesLogged >= probeBudget)
            {
                return;
            }
            string commanded = DescribeUnitAnimation(worker.Id);
            // The reference must be a worker the engine is walking on its own
            // (its tile changed since the previous scan). A standing worker
            // proves nothing about the walk animation, which is what the first
            // probe generation got wrong.
            string reference = "none_walking";
            UnitSnapshot fallback = null;
            foreach (UnitSnapshot candidate in snapshots)
            {
                if (candidate.Id == worker.Id
                    || candidate.Type != worker.Type
                    || candidate.Owner != worker.Owner
                    || _commands.ContainsKey(candidate.Id))
                {
                    continue;
                }
                if (fallback == null)
                {
                    fallback = candidate;
                }
                long previous;
                if (_previousWorkerPositions.TryGetValue(
                        candidate.Id,
                        out previous)
                    && previous != PackTile(candidate.X, candidate.Y))
                {
                    reference = "walking " + DescribeUnitAnimation(candidate.Id);
                    fallback = null;
                    break;
                }
            }
            if (fallback != null)
            {
                reference = "standing " + DescribeUnitAnimation(fallback.Id);
            }
            int probeIndex;
            if (hunterProbe)
            {
                _hunterAnimationProbesLogged++;
                probeIndex = _hunterAnimationProbesLogged;
            }
            else
            {
                _animationProbesLogged++;
                probeIndex = _animationProbesLogged;
            }
            _info(
                "Worker militia animation probe "
                + (hunterProbe ? "hunter " : "woodcutter ")
                + probeIndex.ToString(CultureInfo.InvariantCulture)
                + "/" + probeBudget.ToString(CultureInfo.InvariantCulture)
                + ": commanded[" + commanded + "] reference[" + reference
                + "] occasion=" + occasion
                + " phase=" + MissionPhaseName(command.Phase)
                + " dest="
                + command.ManualDestinationX.ToString(CultureInfo.InvariantCulture)
                + ","
                + command.ManualDestinationY.ToString(CultureInfo.InvariantCulture)
                + ".");
        }

        private static string DescribeUnitAnimation(int unitId)
        {
            if (unitId <= 0
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return "unit_missing";
            }
            ref GameUnit unit = ref pointer.AsRef();
            return "id=" + unitId.ToString(CultureInfo.InvariantCulture)
                + " ai=" + unit.r_AIState.ToString(CultureInfo.InvariantCulture)
                + " anim=" + unit.r_AnimationFrame.ToString(
                    CultureInfo.InvariantCulture)
                + " sprite=" + unit.r_CurrentSpriteAnimationFrame.ToString(
                    CultureInfo.InvariantCulture)
                + " dir=" + unit.r_Direction.ToString()
                // command_mode: the field this feature forces to 1. The engine
                // branches on it in the per-unit update (CrusaderDE.dll
                // 0x184C19/0x184C66), so a walking reference worker showing 0
                // here would explain the frozen sprite of a commanded one.
                + " cmd=" + SeInteropFieldAliases.CommandMode(ref unit).ToString(CultureInfo.InvariantCulture)
                + " path=" + unit.r_PathPlanStateBitFlags.ToString(
                    CultureInfo.InvariantCulture)
                + " moving=" + unit.r_MovementSubstep.ToString(
                    CultureInfo.InvariantCulture)
                + " pathrel=" + unit.r_SelectedConnectionRecordId.ToString(
                    CultureInfo.InvariantCulture)
                + " tgt=" + unit.r_TargetTilePositionX.ToString(
                    CultureInfo.InvariantCulture)
                + "," + unit.r_TargetTilePositionY.ToString(
                    CultureInfo.InvariantCulture)
                + " tgt2=" + unit.r_TargetTilePositionX2.ToString(
                    CultureInfo.InvariantCulture)
                + "," + unit.r_TargetTilePositionY2.ToString(
                    CultureInfo.InvariantCulture)
                + " sel=" + unit.r_UnitHover.ToString(
                    CultureInfo.InvariantCulture)
                + "/" + unit.r_UnitSelected.ToString(
                    CultureInfo.InvariantCulture)
                + " tribe=" + unit.r_TribeId.ToString(
                    CultureInfo.InvariantCulture)
                + " marker=" + unit.N00000062.ToString(
                    CultureInfo.InvariantCulture)
                + " pos=" + unit.r_CurrentWorldPositionX.ToString(
                    CultureInfo.InvariantCulture)
                + "," + unit.r_CurrentWorldPositionY.ToString(
                    CultureInfo.InvariantCulture);
        }

        private static long PackTile(int x, int y)
        {
            return ((long)x << 32) | unchecked((uint)y);
        }

        /// <summary>
        /// Observes every projectile the engine spawns and records the two
        /// numbers this feature is still missing, without touching anything.
        /// </summary>
        /// <remarks>
        /// A hunter shooting wildlife on its own goes through its native
        /// shooting state, and that state is what drives the shot animation the
        /// owner asked for; logging the hunter's AI state at the exact moment
        /// its arrow is created names that state. An archer's arrow gives the
        /// real shooting distance in the same tile units this feature uses for
        /// <c>HunterAttackRange</c>, so "hunter range like archer range" can be
        /// set to a measured value instead of a guessed one.
        /// </remarks>
        private void OnProjectileSpawnObserved(ProjectileSpawnEventArgs e)
        {
            if (e == null
                || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            try
            {
                GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                int shooter = e.SourceUnitId;
                if (!IsPlausibleUnitId(shooter)
                    || units == null
                    || !units.IsValid(shooter))
                {
                    return;
                }
                eChimps type = units.GetType(shooter);
                if (type != eChimps.CHIMP_TYPE_HUNTER
                    && type != eChimps.CHIMP_TYPE_ARCHER)
                {
                    return;
                }
                bool commanded = _commands.ContainsKey(shooter);
                string cohort;
                int sample;
                int previousProjectileTick;
                int simulationTick = SimulationNowMilliseconds();
                if (type == eChimps.CHIMP_TYPE_ARCHER)
                {
                    if (_archerProjectileProbesLogged
                        >= ProjectileProbeFloorPerCohort)
                    {
                        return;
                    }
                    cohort = "vanilla_archer";
                    sample = ++_archerProjectileProbesLogged;
                    previousProjectileTick = _lastArcherProjectileTick;
                    _lastArcherProjectileTick = simulationTick;
                }
                else if (commanded)
                {
                    if (_commandedHunterProjectileProbesLogged
                        >= ProjectileProbeFloorPerCohort)
                    {
                        return;
                    }
                    cohort = "commanded_hunter";
                    sample = ++_commandedHunterProjectileProbesLogged;
                    previousProjectileTick =
                        _lastCommandedHunterProjectileTick;
                    _lastCommandedHunterProjectileTick = simulationTick;
                }
                else
                {
                    if (_naturalHunterProjectileProbesLogged
                        >= ProjectileProbeFloorPerCohort)
                    {
                        return;
                    }
                    cohort = "natural_hunter";
                    sample = ++_naturalHunterProjectileProbesLogged;
                    previousProjectileTick = _lastNaturalHunterProjectileTick;
                    _lastNaturalHunterProjectileTick = simulationTick;
                }
                // The shot's own start and end point, straight out of the
                // event. This is the authoritative distance: it describes the
                // projectile that is actually being created and needs no
                // assumption about what AttackedUnitId refers to.
                //
                // The event states these in WORLD tiles, and the Extender is
                // explicit that one local tile is eight world tiles
                // (GameUnitManagerAPI.GetCurrentWorldTilePosition). The unit
                // fields this feature otherwise uses are LOCAL tiles, so the
                // two must not be compared without the divisor.
                int flightX = e.TargetWorldTileX - e.SourceWorldTileX;
                int flightY = e.TargetWorldTileY - e.SourceWorldTileY;
                long chebyshevMilli =
                    (long)ApproximateTileDistance(flightX, flightY)
                    * 1000L / WorldTilesPerLocalTile;
                long squared = (long)flightX * flightX
                    + (long)flightY * flightY;
                long euclideanMilli = (long)Math.Round(
                    Math.Sqrt(squared) * 1000.0 / WorldTilesPerLocalTile);
                int absoluteFlightX = Math.Abs(flightX);
                int absoluteFlightY = Math.Abs(flightY);
                string axis = flightX == 0 || flightY == 0
                    ? "cardinal"
                    : absoluteFlightX == absoluteFlightY
                        ? "diagonal"
                        : "oblique";
                long configuredBoundaryDeltaMilli = chebyshevMilli
                    - (GeneratedWorkerMilitiaContract.HunterAttackRange
                        * 1000L);
                int cadenceDelta = sample <= 1
                    ? -1
                    : unchecked(simulationTick - previousProjectileTick);
                _info(
                    "Worker militia projectile calibration: cohort=" + cohort
                    + " sample=" + sample.ToString(CultureInfo.InvariantCulture)
                    + "/" + ProjectileProbeFloorPerCohort.ToString(
                        CultureInfo.InvariantCulture)
                    + " shooter=" + type.ToString()
                    + " id=" + shooter.ToString(CultureInfo.InvariantCulture)
                    + " commanded=" + TelemetryBoolean(commanded)
                    + " projectile=" + e.ProjectileType.ToString()
                    + " world_dx=" + flightX.ToString(CultureInfo.InvariantCulture)
                    + " world_dy=" + flightY.ToString(CultureInfo.InvariantCulture)
                    + " local_chebyshev_milli="
                    + chebyshevMilli.ToString(CultureInfo.InvariantCulture)
                    + " local_euclidean_milli="
                    + euclideanMilli.ToString(CultureInfo.InvariantCulture)
                    + " axis=" + axis
                    + " configured_range="
                    + GeneratedWorkerMilitiaContract.HunterAttackRange.ToString(
                        CultureInfo.InvariantCulture)
                    + " boundary_delta_milli="
                    + configuredBoundaryDeltaMilli.ToString(
                        CultureInfo.InvariantCulture)
                    + " simulation_time_ms="
                    + simulationTick.ToString(CultureInfo.InvariantCulture)
                    + " cadence_delta_ms="
                    + cadenceDelta.ToString(CultureInfo.InvariantCulture)
                    + " attacked_unit="
                    + e.AttackedUnitId.ToString(CultureInfo.InvariantCulture)
                    + " shooter_state[" + DescribeUnitAnimation(shooter) + "].");
            }
            catch (Exception exception)
            {
                // Evidence only: never let the probe disturb the game.
                _warning(
                    "Worker militia projectile probe failed harmlessly: "
                    + exception.GetType().Name + ".");
            }
        }

        private static int ApproximateTileDistance(int dx, int dy)
        {
            int ax = dx < 0 ? -dx : dx;
            int ay = dy < 0 ? -dy : dy;
            return ax > ay ? ax : ay;
        }

        /// <summary>
        /// Records every AI-state change of a local militia worker, whether it
        /// is under our command or doing its own job.
        /// </summary>
        /// <remarks>
        /// The engine drives sprites through per-type update functions
        /// (CrusaderDE.dll unit-function vtable: WoodcutterUpdate 0xAA9E0;
        /// 0xABA10 was historically labelled HunterUpdate but inspection found
        /// mostly building-field traffic, so that label remains unverified)
        /// and picks the animation from tables indexed by
        /// <c>r_AnimationTimer</c> (GameUnit +0x2AC, e.g. RVA 0x146AF3/0x146B93).
        /// Which animation runs therefore follows the unit's AI state. A hunter
        /// hunting wildlife on its own walks up and shoots with the animation
        /// the owner wants for combat, so its natural state sequence is the
        /// reference this feature needs; a commanded hunter's sequence next to
        /// it shows exactly which state is missing. Sampling happens in the
        /// existing scan instead of through the Extender's AI-state trackers,
        /// which are installed once at detour construction - before this plugin
        /// can register anything.
        /// </remarks>
        private void LogAiStateTransitions(List<UnitSnapshot> snapshots)
        {
            if (_aiTransitionsLogged >= MaxAiStateTransitions)
            {
                return;
            }
            foreach (UnitSnapshot snapshot in snapshots)
            {
                if (!IsMilitia(snapshot.Type)
                    || snapshot.Owner
                        != GamePlayerManagerAPI.Instance.GetLocalPlayerId()
                    || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                        snapshot.Id,
                        out var pointer))
                {
                    continue;
                }
                ref GameUnit unit = ref pointer.AsRef();
                int state = unit.r_AIState;
                int previous;
                bool known = _aiStateHistory.TryGetValue(
                    snapshot.Id,
                    out previous);
                if (known && previous == state)
                {
                    continue;
                }
                _aiStateHistory[snapshot.Id] = state;
                if (!known)
                {
                    // First sighting is a baseline, not a transition.
                    continue;
                }
                _aiTransitionsLogged++;
                _info(
                    "Worker militia AI-state transition "
                    + _aiTransitionsLogged.ToString(CultureInfo.InvariantCulture)
                    + "/"
                    + MaxAiStateTransitions.ToString(CultureInfo.InvariantCulture)
                    + ": unit=" + UnitName(snapshot.Type)
                    + " id=" + snapshot.Id.ToString(CultureInfo.InvariantCulture)
                    + " " + previous.ToString(CultureInfo.InvariantCulture)
                    + "->" + state.ToString(CultureInfo.InvariantCulture)
                    + " commanded="
                    + (_commands.ContainsKey(snapshot.Id) ? "yes" : "no")
                    + " anim_timer=" + unit.r_AnimationTimer.ToString(
                        CultureInfo.InvariantCulture)
                    + " sprite=" + unit.r_CurrentSpriteAnimationFrame.ToString(
                        CultureInfo.InvariantCulture)
                    + " anim=" + unit.r_AnimationFrame.ToString(
                        CultureInfo.InvariantCulture)
                    + " dir=" + unit.r_Direction.ToString()
                    + " cmd=" + SeInteropFieldAliases.CommandMode(ref unit).ToString(CultureInfo.InvariantCulture)
                    + " moving=" + unit.r_MovementSubstep.ToString(
                        CultureInfo.InvariantCulture)
                    + ".");
                if (_aiTransitionsLogged >= MaxAiStateTransitions)
                {
                    return;
                }
            }
        }

        /// <summary>
        /// Reproduces the native "order accepted" marker the engine flashes on
        /// a commanded unit by writing the pinned countdown at GameUnit +0x78
        /// (see <see cref="NativeCommandMarkerContainerOffset"/>). Only the low
        /// ushort is the counter, so the upper half is preserved. The engine
        /// decrements it back to zero by itself, therefore this write needs no
        /// rollback and can never leave a permanent marker.
        /// </summary>
        private void RaiseNativeCommandMarker(int unitId, string kind)
        {
            if (unitId <= 0
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (unit.r_AliveState != AliveState.IsAlive
                || !IsMilitia(unit.r_UnitChimp)
                || unit.r_ControllableForPlayerId
                    != GamePlayerManagerAPI.Instance.GetLocalPlayerId())
            {
                return;
            }
            // SE 2.x splits the former UInt32 at +0x78 into two UInt16
            // halves; writing the low half alone is exactly the old
            // "keep bits 16..31" update.
            unit.N00000062 = unchecked((ushort)NativeCommandMarkerValue);
            if (_evidenceLogged.Add("command_marker." + kind))
            {
                _info(
                    "Worker militia raised the native command marker for a "
                    + kind + " order: unit_id="
                    + unitId.ToString(CultureInfo.InvariantCulture)
                    + " counter="
                    + NativeCommandMarkerValue.ToString(
                        CultureInfo.InvariantCulture)
                    + " (the engine fades and clears it by itself).");
            }
        }

        /// <summary>
        /// Every unit type the player can give orders to, i.e. everything that
        /// must already carry the command-cursor bits.
        /// </summary>
        /// <remarks>
        /// The first version of this list held six types and silently matched
        /// nothing at all on a Crusader map, because the enemy there is Arab
        /// and none of those types were listed (measured 2026-08-21: the
        /// soldier probe was never even called). It is therefore spelled out in
        /// full and pinned by a contract test. Civilians, animals, the lord,
        /// the lady and the militia workers themselves stay out.
        /// </remarks>
        /// <summary>
        /// Guards every unit id before it reaches the Extender's API. A garbage
        /// id produced five [Error] lines per game on 2026-08-21.
        /// </summary>
        private static string SafeUnitName(int unitId)
        {
            return IsPlausibleUnitId(unitId)
                ? UnitName(GameUnitManagerAPI.Instance.GetType(unitId))
                : "unknown";
        }

        private static bool IsPlausibleUnitId(int unitId)
        {
            return unitId > 0 && unitId < NativeMaxUnitId;
        }

        /// <summary>
        /// Records the AI state the engine itself drives a walking worker with.
        /// </summary>
        /// <remarks>
        /// Only workers this feature does not command are used, and only when
        /// their map tile changed since the previous scan - a standing worker
        /// proves nothing. The value is therefore the engine's own answer for
        /// that unit type, never a guess.
        /// </remarks>
        /// <summary>
        /// Sammelt im Scan (Hauptfaden) die Kennungen, die die Kegel-Messung
        /// spaeter auf dem Engine-Faden nur noch nachschlagen muss.
        /// </summary>
        /// <remarks>
        /// Ohne diesen Umweg haette die Messung GetAllAliveUnits() im
        /// EngineInterface.run-Postfix gerufen. Native Extender-Abfragen aus
        /// diesem Kontext beenden das Spiel ohne Absturzbericht - eine Sonde
        /// darf niemals das Risiko sein, das sie untersuchen soll.
        /// </remarks>
        private void CollectMeasurementReferences(List<UnitSnapshot> snapshots)
        {
            ConeUnitSample soldier = null;
            var militia = new Dictionary<int, ConeUnitSample>();
            var ownTiles = new List<long>(64);
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            foreach (UnitSnapshot snapshot in snapshots)
            {
                if (snapshot == null
                    || snapshot.Owner != localPlayer)
                {
                    continue;
                }
                long previousTile;
                bool wasMoving = IsMilitia(snapshot.Type)
                    && !_commands.ContainsKey(snapshot.Id)
                    && _previousWorkerPositions.TryGetValue(
                        snapshot.Id,
                        out previousTile)
                    && previousTile != PackTile(snapshot.X, snapshot.Y);
                var sample = new ConeUnitSample(
                    snapshot.Id,
                    (int)snapshot.Type,
                    snapshot.TileId,
                    wasMoving);
                if (ownTiles.Count < 64)
                {
                    ownTiles.Add(snapshot.TileId);
                }
                if (IsMilitia(snapshot.Type))
                {
                    militia[snapshot.Id] = sample;
                }
                if (soldier == null
                    && !IsMilitia(snapshot.Type)
                    && IsCommandableSoldier(snapshot.Type))
                {
                    soldier = sample;
                }
            }
            // Reference publication is atomic; every object reachable from
            // these references is complete and never mutated afterwards.
            Volatile.Write(ref _measureMilitiaUnits, militia);
            Volatile.Write(ref _measureSoldier, soldier);
            Volatile.Write(ref _measureOwnUnitTiles, ownTiles.ToArray());
        }

        private void LearnWalkStates(List<UnitSnapshot> snapshots)
        {
            foreach (UnitSnapshot snapshot in snapshots)
            {
                if (!IsMilitia(snapshot.Type)
                    || _commands.ContainsKey(snapshot.Id))
                {
                    continue;
                }
                long previous;
                if (!_previousWorkerPositions.TryGetValue(
                        snapshot.Id,
                        out previous)
                    || previous == PackTile(snapshot.X, snapshot.Y))
                {
                    continue;
                }
                if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                        snapshot.Id,
                        out var pointer))
                {
                    continue;
                }
                ref GameUnit unit = ref pointer.AsRef();
                if (unit.r_AliveState != AliveState.IsAlive)
                {
                    continue;
                }
                LearnWalkSpriteBase(
                    snapshot.Type,
                    unit.r_CurrentSpriteAnimationFrame);
                int state = unit.r_AIState;
                Dictionary<int, int> counts;
                if (!_walkStateCounts.TryGetValue(snapshot.Type, out counts))
                {
                    counts = new Dictionary<int, int>();
                    _walkStateCounts[snapshot.Type] = counts;
                }
                int seen;
                counts[state] = counts.TryGetValue(state, out seen)
                    ? seen + 1
                    : 1;

                // Majority wins, and only above a floor. A moving worker can be
                // walking to a tree, carrying wood home or doing something else
                // entirely, so a single sighting proves nothing: the 20:25 run
                // collected 9, 1, 4, 0, 8, 121 and 111 for the woodcutter and
                // the last one always won, which put commanded workers into
                // nonsense states.
                int best = -1;
                int bestCount = 0;
                foreach (KeyValuePair<int, int> pair in counts)
                {
                    if (pair.Value > bestCount)
                    {
                        bestCount = pair.Value;
                        best = pair.Key;
                    }
                }
                if (bestCount < WalkStateEvidenceFloor)
                {
                    continue;
                }
                int known;
                if (_observedWalkState.TryGetValue(snapshot.Type, out known)
                    && known == best)
                {
                    continue;
                }
                _observedWalkState[snapshot.Type] = best;
                if (_evidenceLogged.Add(
                        "walk_state." + snapshot.Type + "." + best))
                {
                    _info(
                        "Worker militia learned the engine's own walking AI"
                        + " state for " + UnitName(snapshot.Type) + ": state="
                        + best.ToString(CultureInfo.InvariantCulture)
                        + " observations="
                        + bestCount.ToString(CultureInfo.InvariantCulture)
                        + " (majority over uncommanded workers whose tile"
                        + " changed).");
                }
            }
        }

        /// <summary>
        /// Majority-learns the walking sprite base for a worker type from a
        /// free, moving reference of that type. Same discipline as the walk AI
        /// state: a floor of sightings, majority wins.
        /// </summary>
        private void LearnWalkSpriteBase(eChimps type, uint spriteBase)
        {
            int value = unchecked((int)spriteBase);
            Dictionary<int, int> counts;
            if (!_walkSpriteCounts.TryGetValue(type, out counts))
            {
                counts = new Dictionary<int, int>();
                _walkSpriteCounts[type] = counts;
            }
            int seen;
            counts[value] = counts.TryGetValue(value, out seen) ? seen + 1 : 1;
            int best = -1;
            int bestCount = 0;
            foreach (KeyValuePair<int, int> pair in counts)
            {
                if (pair.Value > bestCount)
                {
                    bestCount = pair.Value;
                    best = pair.Key;
                }
            }
            if (bestCount < WalkStateEvidenceFloor)
            {
                return;
            }
            int known;
            if (_observedWalkSprite.TryGetValue(type, out known) && known == best)
            {
                return;
            }
            _observedWalkSprite[type] = best;
            if (_evidenceLogged.Add("walk_sprite." + type + "." + best))
            {
                _info(
                    "Worker militia learned the engine's own walking sprite"
                    + " base for " + UnitName(type) + ": base="
                    + best.ToString(CultureInfo.InvariantCulture)
                    + " observations="
                    + bestCount.ToString(CultureInfo.InvariantCulture)
                    + " (majority over uncommanded workers whose tile changed).");
            }
        }

        /// <summary>
        /// Retains the disabled sprite-base experiment for controlled evidence
        /// only. It must not run without an explicit reviewed calibration.
        /// </summary>
        /// <remarks>
        /// REFUTED 2026-08-30: r_CurrentSpriteAnimationFrame (+0x44) is not a
        /// stable walking constant per worker type. Different games produced
        /// different majority values, and an early five-sample write held the
        /// wrong value for the whole command. The current generated contract
        /// therefore keeps WorkerAnimationCalibrated=false. This method is not
        /// the crouch-slide fix; the native move-state branch is the current
        /// implementation under test. Identity checks remain here so a future
        /// explicitly calibrated experiment cannot write through a stale
        /// command.
        /// </remarks>
        private void ApplyLearnedWalkSprite(CommandState command, bool isMoving)
        {
            if (!isMoving)
            {
                return;
            }
            CommandState liveCommand;
            bool liveCommandOwnsWorker = command != null
                && _commands.TryGetValue(command.WorkerUnitId, out liveCommand)
                && ReferenceEquals(liveCommand, command)
                && liveCommand.Generation == command.Generation;
            bool exactCommandIdentity = command != null
                && CommandMatchesLiveWorkerProvenance(
                    command,
                    command.WorkerUnitId);
            if (!WorkerMilitiaSafetyRules.CanApplyAnimationState(
                    GeneratedWorkerMilitiaContract.WorkerAnimationCalibrated,
                    exactCommandIdentity,
                    liveCommandOwnsWorker))
            {
                return;
            }
            int unitId = command.WorkerUnitId;
            eChimps type = command.WorkerType;
            int spriteBase;
            if (unitId <= 0
                || !_observedWalkSprite.TryGetValue(type, out spriteBase)
                || spriteBase < 0
                || spriteBase > ushort.MaxValue
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (unit.r_AliveState != AliveState.IsAlive
                || unit.r_UnitChimp != type
                || unchecked((int)unit.r_GlobalId) != command.WorkerGlobalId
                || unit.r_ControllableForPlayerId != command.WorkerOwner
                || SeInteropFieldAliases.CommandMode(ref unit) != 1
                || unit.r_CurrentSpriteAnimationFrame == (uint)spriteBase)
            {
                return;
            }
            if (!CommandMatchesLiveWorkerProvenance(command, unitId))
            {
                return;
            }
            uint previous = unit.r_CurrentSpriteAnimationFrame;
            unit.r_CurrentSpriteAnimationFrame = (uint)spriteBase;
            if (unit.r_CurrentSpriteAnimationFrame != (uint)spriteBase)
            {
                if (_evidenceLogged.Add("walk_sprite_readback_failed." + type))
                {
                    _warning(
                        "Worker militia could not verify its walking sprite-base"
                        + " write for " + UnitName(type) + "; no further sprite"
                        + " base is written to that command.");
                }
                return;
            }
            if (_evidenceLogged.Add("walk_sprite_applied." + type))
            {
                _info(
                    "Worker militia put a commanded " + UnitName(type)
                    + " onto the engine's walking sprite base: was="
                    + previous.ToString(CultureInfo.InvariantCulture)
                    + " now=" + spriteBase.ToString(CultureInfo.InvariantCulture)
                    + " unit_id=" + unitId.ToString(CultureInfo.InvariantCulture)
                    + " (disabled sprite-base experiment was explicitly enabled).");
            }
        }

        /// <summary>
        /// Puts a commanded worker into a calibrated walking AI state, but only
        /// while the exact live command still owns that exact worker.
        /// </summary>
        /// <remarks>
        /// Observing a majority state is useful evidence, not authority to
        /// mutate <c>r_AIState</c>. The write remains disabled until the
        /// generated contract names reviewed evidence. Once enabled, identity
        /// and ownership are checked both before resolving the pointer and
        /// immediately before the write; readback is mandatory.
        /// </remarks>
        private void ApplyLearnedWalkState(CommandState command)
        {
            CommandState liveCommand;
            bool liveCommandOwnsWorker = command != null
                && _commands.TryGetValue(
                    command.WorkerUnitId,
                    out liveCommand)
                && ReferenceEquals(liveCommand, command)
                && liveCommand.Generation == command.Generation;
            bool exactCommandIdentity = command != null
                && CommandMatchesLiveWorkerProvenance(
                    command,
                    command.WorkerUnitId);
            // Eigener Schalter: die Spur vom 30.08. widerspricht dem Lerner
            // beim AI-Zustand (Holzfaeller 9 aus fuenf Beobachtungen, waehrend
            // der freie Laeufer ueber 90 Takte 1 zeigte). Die Sprite-Basis ist
            // belegt, der Zustand nicht - also getrennt schaltbar.
            if (!WorkerMilitiaSafetyRules.CanApplyAnimationState(
                    GeneratedWorkerMilitiaContract.WorkerWalkStateCalibrated,
                    exactCommandIdentity,
                    liveCommandOwnsWorker))
            {
                return;
            }
            int unitId = command.WorkerUnitId;
            eChimps type = command.WorkerType;
            int walkState;
            if (unitId <= 0
                || !_observedWalkState.TryGetValue(type, out walkState)
                || walkState < ushort.MinValue
                || walkState > ushort.MaxValue
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (unit.r_AliveState != AliveState.IsAlive
                || unit.r_UnitChimp != type
                || unchecked((int)unit.r_GlobalId)
                    != command.WorkerGlobalId
                || unit.r_ControllableForPlayerId != command.WorkerOwner
                || SeInteropFieldAliases.CommandMode(ref unit) != 1
                || unit.r_AIState == walkState)
            {
                return;
            }
            if (!_commands.TryGetValue(unitId, out liveCommand)
                || !ReferenceEquals(liveCommand, command)
                || liveCommand.Generation != command.Generation)
            {
                return;
            }
            int previous = unit.r_AIState;
            unit.r_AIState = (ushort)walkState;
            if (unit.r_AIState != walkState)
            {
                if (_evidenceLogged.Add("walk_state_readback_failed." + type))
                {
                    _warning(
                        "Worker militia could not verify its calibrated "
                        + "walking AI-state write for " + UnitName(type)
                        + "; no further animation state is written to that "
                        + "command.");
                }
                return;
            }
            if (!CommandMatchesLiveWorkerProvenance(command, unitId))
            {
                if (_evidenceLogged.Add(
                        "walk_state_identity_changed." + type))
                {
                    _warning(
                        "Worker militia observed worker identity change after "
                        + "a calibrated walking-state write. The prior state "
                        + "is not restored through the now-unowned pointer.");
                }
                return;
            }
            if (_evidenceLogged.Add("walk_state_applied." + type))
            {
                _info(
                    "Worker militia put a commanded " + UnitName(type)
                    + " into the engine's walking AI state: was="
                    + previous.ToString(CultureInfo.InvariantCulture)
                    + " now=" + walkState.ToString(CultureInfo.InvariantCulture)
                    + " unit_id=" + unitId.ToString(CultureInfo.InvariantCulture)
                    + ".");
            }
        }

        /// <summary>
        /// Gives the selected militia worker the same command cursor the engine
        /// draws for a real soldier.
        /// </summary>
        /// <remarks>
        /// The cursor kind is a single global at
        /// <see cref="NativeCursorKindRva"/>. For a militia worker the pinned
        /// input handler always writes -10 ("order not possible"), because the
        /// worker's type fails a gate at RVA 0x8E398. A measurement on
        /// 2026-08-19 refuted satisfying that gate through the per-type
        /// capability table, so the value is corrected afterwards instead.
        ///
        /// Which numbers mean "move" and "attack" is never guessed: they are
        /// read off the engine while the player has an ordinary troop
        /// selection - open ground yields the move cursor, an enemy the attack
        /// cursor. Only once observed are they replayed, and only while our own
        /// worker is the confirmed, commandable selection. The write happens in
        /// the EngineInterface.run postfix, after the native handler has
        /// decided for that frame.
        /// </remarks>
        private int[] ReadCursorBlock(long baseAddress)
        {
            var block = new int[NativeCursorBlockDwords];
            for (int i = 0; i < NativeCursorBlockDwords; i++)
            {
                block[i] = Marshal.ReadInt32(new IntPtr(
                    baseAddress + NativeCursorBlockRva + (i * 4)));
            }
            return block;
        }

        private void WriteCursorBlock(long baseAddress, int[] block)
        {
            for (int i = 0; i < NativeCursorBlockDwords; i++)
            {
                Marshal.WriteInt32(
                    new IntPtr(baseAddress + NativeCursorBlockRva + (i * 4)),
                    block[i]);
            }
        }

        private static bool CursorBlocksMatch(int[] a, int[] b)
        {
            if (a == null || b == null)
            {
                return false;
            }
            for (int i = 0; i < NativeCursorBlockDwords; i++)
            {
                if (a[i] != b[i])
                {
                    return false;
                }
            }
            return true;
        }

        private static string DescribeCursorBlock(int[] block)
        {
            if (block == null)
            {
                return "none";
            }
            string text = string.Empty;
            for (int i = 0; i < NativeCursorBlockDwords; i++)
            {
                if (i > 0)
                {
                    text += ",";
                }
                text += block[i].ToString(CultureInfo.InvariantCulture);
            }
            return text;
        }

        /// <summary>
        /// Gives the selected militia worker the same command cursor the engine
        /// draws for a real soldier.
        /// </summary>
        /// <remarks>
        /// For a militia worker the pinned input handler always takes the
        /// branch at RVA 0x8E3EA, which writes the "order not possible" cursor.
        /// Two earlier attempts were refuted by measurement: satisfying the
        /// per-type capability gate at 0x8E398 (not decidable from the table),
        /// and writing cursor_kind alone (no visible change, because the
        /// graphic comes from the neighbouring globals).
        ///
        /// So the whole cursor block is captured off the engine itself while
        /// the player has an ordinary troop selection - open ground gives the
        /// move cursor, an enemy the attack cursor - and replayed verbatim for
        /// our own worker. Nothing is guessed, and nothing is written before
        /// both variants have been seen. The write happens in the
        /// EngineInterface.run postfix, after the native handler decided for
        /// that frame.
        /// </remarks>
        /// <summary>
        /// The one measurement that decides whether the class patch worked:
        /// with a militia worker confirmed as the commandable selection, it
        /// prints the engine's own selected-class counters next to the cursor
        /// kind it produced.
        /// </summary>
        /// <remarks>
        /// Before the patch every counter is zero and the kind is -10. After
        /// it exactly one counter must read 1 - the archer class for a hunter,
        /// the maceman class for a woodcutter - and the kind must be one of the
        /// engine's own command cursors. Capped, because this runs per input
        /// tick.
        /// </remarks>
        /// <summary>
        /// Je Unity-Takt: alle Animationsfelder des kommandierten Arbeiters und
        /// eines freien Arbeiters desselben Typs nebeneinander. Reine Lesung.
        /// </summary>
        /// <remarks>
        /// Zwei Animationstheorien sind an zu grober Abtastung gescheitert. Die
        /// Scansonde lief alle 250 ms und verglich Momentaufnahmen; damit ist
        /// nicht zu sehen, welches Feld beim freien Laeufer fortschreitet und
        /// beim kommandierten stehenbleibt. Diese Spur laeuft je Takt, deckt
        /// 90 Takte (rund 1,5 Sekunden) ab und enthaelt unter anderem
        /// r_GameMaterialIndex - die GM-Gruppe, also den Sprite-SATZ, der nie
        /// gemessen wurde.
        /// </remarks>
        private void LogAnimationTrace()
        {
            int commandedId = 0;
            long generation = 0;
            eChimps commandedType = eChimps.CHIMP_TYPE_NULL;
            int referenceId = 0;
            int traceOrdinal = 0;
            string orderPath = null;
            bool homeless = false;
            // Alles unter der Sperre entscheiden und kopieren. Eine Iteration
            // ueber _commands/_previousWorkerPositions ohne Sperre kann durch
            // eine gleichzeitige Aenderung werfen; der Fang darum herum haette
            // die Sonde still gemacht statt sie zu melden.
            lock (_gate)
            {
                if (!IsOperationalLocked())
                {
                    return;
                }
                foreach (CommandState command in _commands.Values)
                {
                    if (command.Phase == MissionPhase.Outbound)
                    {
                        commandedId = command.WorkerUnitId;
                        commandedType = command.WorkerType;
                        generation = command.Generation;
                        orderPath = command.OrderPath;
                        homeless = command.Homeless;
                        break;
                    }
                }
                if (commandedId <= 0)
                {
                    return;
                }
                // Ein neuer Befehl auf denselben Arbeiter bekommt eine neue
                // Spur. Diese Pruefung muss VOR dem Budgetabbruch liegen;
                // andernfalls kann ein einmal ausgeschoepfter erster Befehl
                // jede spaetere Spur der Sitzung dauerhaft unterdruecken.
                if (_animationTraceCommandId != commandedId
                    || _animationTraceGeneration != generation)
                {
                    _animationTraceCommandId = commandedId;
                    _animationTraceGeneration = generation;
                    _animationTraceLogged = 0;
                }
                if (_animationTraceLogged >= MaxAnimationTraceLogs)
                {
                    return;
                }
                Dictionary<int, ConeUnitSample> measurement = Volatile.Read(
                    ref _measureMilitiaUnits);
                if (measurement != null)
                {
                    foreach (ConeUnitSample candidate in measurement.Values)
                    {
                        if (candidate.Id == commandedId
                            || candidate.Type != (int)commandedType
                            || !candidate.WasMoving
                            || _commands.ContainsKey(candidate.Id)
                            || !IsPlausibleUnitId(candidate.Id))
                        {
                            continue;
                        }
                        referenceId = candidate.Id;
                        break;
                    }
                }
                traceOrdinal = ++_animationTraceLogged;
            }
            _info(
                "Worker militia anim trace "
                + traceOrdinal.ToString(CultureInfo.InvariantCulture)
                + "/" + MaxAnimationTraceLogs.ToString(
                    CultureInfo.InvariantCulture)
                + " type=" + UnitName(commandedType)
                + " order_path=" + (orderPath ?? "none")
                + " homeless=" + TelemetryBoolean(homeless)
                + " commanded["
                + WorkerMilitiaMeasurement.DescribeAnimationFields(commandedId)
                + "] free["
                + (referenceId > 0
                    ? WorkerMilitiaMeasurement.DescribeAnimationFields(
                        referenceId)
                    : "none")
                + "] combat["
                + WorkerMilitiaMeasurement.DescribeCombatFields(commandedId)
                + "].");
        }

        private void LogCommandClassEvidence(
            long baseAddress,
            int workerId,
            int cursorKind,
            int hoveredUnit,
            int hoveredBuilding,
            bool hoveredEnemy)
        {
            if (_commandClassEvidenceLogged >= MaxCommandClassEvidenceLogs)
            {
                return;
            }
            // Eine Zeile je unterschiedlicher Cursorlage statt der ersten
            // sechs ueberhaupt. Sonst entscheidet der Zufall des ersten
            // Sekundenbruchteils, welche Lage gemessen wird.
            string context = "kind=" + cursorKind.ToString(
                    CultureInfo.InvariantCulture)
                + (hoveredEnemy
                    ? "|enemy"
                    : hoveredUnit > 0
                        ? "|unit"
                        : hoveredBuilding > 0
                            ? "|building"
                            : "|ground")
                + "|type=" + SafeUnitName(workerId);
            if (!_commandClassEvidenceContexts.Add(context))
            {
                return;
            }
            _commandClassEvidenceLogged++;
            var counters = new System.Text.StringBuilder();
            int total = 0;
            for (int slot = 0; slot < NativeSelectionClassCounterCount; slot++)
            {
                int value = WorkerMilitiaCommandClass.ReadClassCounter(
                    baseAddress,
                    NativeUnitManagerRva,
                    NativeSelectionClassCounterBase + (slot * 4));
                total += value;
                if (value == 0)
                {
                    continue;
                }
                if (counters.Length > 0)
                {
                    counters.Append(',');
                }
                counters.Append("+0x");
                counters.Append(
                    (NativeSelectionClassCounterBase + (slot * 4)).ToString(
                        "X", CultureInfo.InvariantCulture));
                counters.Append('=');
                counters.Append(value.ToString(CultureInfo.InvariantCulture));
            }
            _info(
                "Worker militia command-class evidence: unit_id="
                + workerId.ToString(CultureInfo.InvariantCulture)
                + " type=" + SafeUnitName(workerId)
                + " patch=" + (_commandClass == null
                    ? "absent"
                    : _commandClass.Evidence)
                + " class_counters="
                + (counters.Length == 0 ? "all_zero" : counters.ToString())
                + " counted=" + total.ToString(CultureInfo.InvariantCulture)
                + " cursor_kind="
                + cursorKind.ToString(CultureInfo.InvariantCulture)
                + " hovered_unit="
                + hoveredUnit.ToString(CultureInfo.InvariantCulture)
                + " hovered_building="
                + hoveredBuilding.ToString(CultureInfo.InvariantCulture)
                + " hovered_enemy=" + hoveredEnemy.ToString()
                + " " + WorkerMilitiaMeasurement.DescribeCommandTarget(
                    baseAddress,
                    NativeUnitManagerRva)
                + " " + DescribeConeTileGate(baseAddress, workerId)
                + ".");
        }

        // One of the cone's native gates - and, since 2026-08-29, known NOT
        // to be the one that was failing. The handler at 0x8E137 first asks
        // 0x18C1A0 which unit is being commanded; for a militia-only selection
        // that answered -1, and every later "imul index,0x490" then indexed
        // BEHIND the unit array. The tile this gate tested was therefore never
        // the worker's tile, which is why "cone_gate_passes=False" never
        // matched anything measurable. With the command-target chain patched,
        // r14 is the worker and this test finally reads its real tile - so the
        // reading below becomes meaningful for the first time. It is:
        //     test dword [rdi+rdx*4+0x898400],0x10000100   ; rdi=0x405CD10
        // i.e. the map-flag word for the unit's own tile, array at RVA
        // 0x48F5110 (= 0x405CD10 + 0x898400), indexed by r_CurrentPositionTileId.
        // Logging the worker's flag word next to a real soldier's turns "the
        // cone still fails" into a named tile-flag difference, if that is the
        // gate, without another disassembly pass.
        private static int NativeConeTileFlagArrayRva { get { return NativeLayout.TileFlagArrayRva; } }
        private const uint NativeConeTileFlagMask = 0x10000100u;

        // Der Cursor-Kachelzeiger des Eingabehandlers. Im Disassembly laedt
        // 0x8E341 "mov edx,[rel 0x3A0FD88]" genau diese Kachel, bevor die
        // Gatterkette laeuft - das ist die Kachel UNTER DER MAUS.
        private static int NativeCursorTileRva { get { return NativeLayout.CursorTileRva; } }

        /// <summary>
        /// Die vollstaendige Kegel-Messung: das Gatter fuer den Arbeiter, fuer
        /// einen echten eigenen Soldaten, fuer die Kachel unter der Maus, und
        /// ein Histogramm der Kachelflaggen aller eigenen Einheiten.
        /// </summary>
        /// <remarks>
        /// Der Lauf vom 29.08. hat gezeigt: das Gatter bei 0x8E398 scheitert
        /// (Kachel 0x00008000 gegen Maske 0x10000100). Was daraus NICHT folgt:
        /// ob die Kachel eines echten Soldaten die Bits traegt. Genau das
        /// entscheidet, ob es um Gelaende geht oder um eine auswahlabhaengige
        /// Erreichbarkeitskarte - und genau das misst diese Zeile.
        /// Reine Lesung, kein Schreibzugriff.
        /// </remarks>
        private string DescribeConeTileGate(long baseAddress, int workerId)
        {
            try
            {
                Dictionary<int, ConeUnitSample> militia = Volatile.Read(
                    ref _measureMilitiaUnits);
                ConeUnitSample workerSample = null;
                if (militia != null)
                {
                    militia.TryGetValue(workerId, out workerSample);
                }
                string worker = workerSample != null
                    ? WorkerMilitiaMeasurement.DescribeConeGate(
                        baseAddress,
                        "worker",
                        workerSample.Id,
                        workerSample.Type,
                        workerSample.TileId)
                    : "worker=no_main_thread_snapshot";
                long cursorTile = Marshal.ReadInt32(
                    new IntPtr(baseAddress + NativeCursorTileRva));
                string cursor = WorkerMilitiaMeasurement.DescribeTileFlags(
                    baseAddress,
                    "cursor",
                    cursorTile);
                // Beides im Scan auf dem Hauptfaden gesammelt. Hier wird nur
                // noch nachgeschlagen und gepinnter Speicher gelesen - keine
                // Extender-Aufzaehlung auf dem Engine-Faden.
                ConeUnitSample soldierSample = Volatile.Read(
                    ref _measureSoldier);
                long[] ownTiles = Volatile.Read(ref _measureOwnUnitTiles);
                string soldier = soldierSample != null
                    ? WorkerMilitiaMeasurement.DescribeConeGate(
                        baseAddress,
                        "soldier",
                        soldierSample.Id,
                        soldierSample.Type,
                        soldierSample.TileId)
                    : "soldier=none_owned";
                string histogram =
                    WorkerMilitiaMeasurement.DescribeTileFlagHistogram(
                        baseAddress,
                        ownTiles ?? Array.Empty<long>(),
                        64);
                return worker + " " + cursor + " " + soldier + " " + histogram;
            }
            catch (Exception)
            {
                return "cone_measure=failed";
            }
        }

        /// <summary>Einheitentypen, fuer die die Engine selbst einen
        /// Befehlskegel zeichnet - die Vergleichsgruppe der Messung.</summary>
        private static bool IsCommandableSoldier(eChimps type)
        {
            switch (type)
            {
                case eChimps.CHIMP_TYPE_ARCHER:
                case eChimps.CHIMP_TYPE_XBOWMAN:
                case eChimps.CHIMP_TYPE_PIKEMAN:
                case eChimps.CHIMP_TYPE_MACEMAN:
                case eChimps.CHIMP_TYPE_SWORDSMAN:
                case eChimps.CHIMP_TYPE_KNIGHT:
                case eChimps.CHIMP_TYPE_LADDERMAN:
                case eChimps.CHIMP_TYPE_ENGINEER:
                case eChimps.CHIMP_TYPE_TUNNELER:
                case eChimps.CHIMP_TYPE_MONK:
                    return true;
                default:
                    return false;
            }
        }

        private bool ValidateCommandClassCounters(
            long baseAddress,
            int workerId)
        {
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                if (lease == null
                    || !lease.CommandClassApplied
                    || _commandClassLeaseGeneration != lease.Generation
                    || lease.UnitId != workerId
                    || _commandClass == null
                    || !_commandClass.IsApplied)
                {
                    FailCommandClassLeaseLocked(
                        "confirmed worker has no exact active class lease",
                        false,
                        true);
                    return false;
                }
                // Der Zensus gehoert der Engine. Er wird bei RVA 0x196F90 in
                // ihrem eigenen Eingabetakt neu aufgebaut - nicht von uns und
                // nicht zwingend in demselben nativen Lauf, in dem wir den
                // Klassenpatch angelegt haben. Vor dem naechsten Lauf sagen die
                // Zaehler daher nichts ueber unseren Eingriff aus, und ein
                // Rueckschluss aus ihnen waere ein Rueckschluss aus dem Stand
                // von vorher.
                if (lease.CommandClassRunGeneration > 0
                    && _nativeRunGeneration <= lease.CommandClassRunGeneration)
                {
                    return false;
                }
                if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                        lease.UnitId,
                        out var pointer))
                {
                    FailCommandClassLeaseLocked(
                        "confirmed class-lease worker disappeared before counter readback",
                        true,
                        false);
                    return false;
                }
                ref GameUnit unit = ref pointer.AsRef();
                if (!SelectionLeaseIdentityMatches(lease, ref unit))
                {
                    FailCommandClassLeaseLocked(
                        "confirmed class-lease worker changed identity before counter readback",
                        true,
                        false);
                    return false;
                }

                int expectedOffset = lease.Type == eChimps.CHIMP_TYPE_HUNTER
                    ? NativeSelectionClassCounterBase
                    : NativeSelectionClassCounterBase + (2 * sizeof(int));
                int total = 0;
                bool exact = true;
                var observed = new System.Text.StringBuilder();
                try
                {
                    for (int slot = 0;
                        slot < NativeSelectionClassCounterCount;
                        slot++)
                    {
                        int offset = NativeSelectionClassCounterBase
                            + (slot * sizeof(int));
                        int value = WorkerMilitiaCommandClass.ReadClassCounter(
                            baseAddress,
                            NativeUnitManagerRva,
                            offset);
                        int expected = offset == expectedOffset ? 1 : 0;
                        total += value;
                        exact &= value == expected;
                        if (value != 0)
                        {
                            if (observed.Length > 0)
                            {
                                observed.Append(',');
                            }
                            observed.Append("+0x");
                            observed.Append(
                                offset.ToString("X", CultureInfo.InvariantCulture));
                            observed.Append('=');
                            observed.Append(
                                value.ToString(CultureInfo.InvariantCulture));
                        }
                    }
                }
                catch (Exception exception)
                {
                    FailCommandClassLeaseLocked(
                        "class-counter readback threw "
                            + exception.GetType().Name,
                        false,
                        true);
                    return false;
                }
                exact &= total == 1;
                if (exact)
                {
                    return true;
                }

                string evidence =
                    "class counters disagree (type=" + UnitName(lease.Type)
                        + " expected=+0x"
                        + expectedOffset.ToString("X", CultureInfo.InvariantCulture)
                        + "=1 observed="
                        + (observed.Length == 0
                            ? "all_zero"
                            : observed.ToString())
                        + " total="
                        + total.ToString(CultureInfo.InvariantCulture) + ")";

                if (total == 0)
                {
                    // Der Zensus hat diese Auswahl noch nicht gezaehlt. Das ist
                    // ein Zeitzustand, kein Widerspruch: einmal sagen und im
                    // naechsten Lauf erneut hinsehen. Die Pacht bleibt stehen -
                    // sie abzureissen wuerde genau die Auswahl beenden, deren
                    // Zaehlung wir gerade abwarten.
                    if (_evidenceLogged.Add(
                            "command_class_census_pending." + lease.Type))
                    {
                        _info(
                            "Worker militia found the native class census not "
                            + "yet rebuilt for its selection (" + evidence
                            + "). The census belongs to the engine's own input "
                            + "tick; the reading is repeated on the next "
                            + "native run instead of being treated as a "
                            + "contradiction.");
                    }
                    return false;
                }

                // total == 1 mit dem FALSCHEN Zaehler heisst: unsere
                // Spenderzuordnung trifft nicht zu, was die Engine tatsaechlich
                // zaehlt. Das ist ein echter innerer Widerspruch - da ist der
                // Eingriff selbst falsch, und weiterzumachen waere blind.
                // total > 1 heisst dagegen nur, dass sich die Auswahl unter uns
                // geaendert hat, obwohl die Einzelauswahlpruefung sie noch als
                // Einzelauswahl sah. Das ist ein Rennen mit dem Spieler, kein
                // Widerspruch, und darf die Miliz nicht fuer die Sitzung
                // abschalten.
                FailCommandClassLeaseLocked(
                    evidence
                        + (total == 1
                            ? " kind=wrong_class"
                            : " kind=selection_changed"),
                    false,
                    total == 1);
                return false;
            }
        }

        private void ObserveAndReplayCommandCursor()
        {
            if (_nativeModuleBase == IntPtr.Zero
                || !_mapApplied
                || _networkSuppressed
                || _selectionQuarantineSuppressed
                || GamePlayerManagerAPI.Instance == null)
            {
                return;
            }
            long baseAddress = _nativeModuleBase.ToInt64();
            int[] current = ReadCursorBlock(baseAddress);
            int kind = current[NativeCursorKindBlockIndex];
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            if (localPlayer < 1 || localPlayer > 8)
            {
                return;
            }
            int nativeSelected = Marshal.ReadInt32(new IntPtr(
                baseAddress + NativeUnitManagerRva
                + SelectedCountOffsetForPlayer(localPlayer)));
            int hoveredUnit = GamePlayerManagerAPI.Instance.GetHoveredUnitId();
            int hoveredBuilding =
                GamePlayerManagerAPI.Instance.GetHoveredBuildingId();
            bool hoveredEnemy = hoveredUnit > 0
                && IsEnemyOfLocalPlayer(hoveredUnit);
            bool plainGround = hoveredUnit == 0 && hoveredBuilding == 0;

            int workerId;
            bool ourMilitia = HasConfirmedCommandableMilitia(out workerId);

            if (ourMilitia)
            {
                if (!ValidateCommandClassCounters(baseAddress, workerId))
                {
                    return;
                }
                LogCommandClassEvidence(
                    baseAddress,
                    workerId,
                    kind,
                    hoveredUnit,
                    hoveredBuilding,
                    hoveredEnemy);
            }

            // Once the active class patch makes the engine itself accept the
            // worker as commandable, its own cursor is authoritative and must
            // not be overwritten by the legacy replay path.
            if (ourMilitia && _commandClass != null && _commandClass.IsApplied)
            {
                return;
            }

            if (!ourMilitia)
            {
                // -10 is the refusal this feature is trying to get rid of and
                // -1 means "no cursor at all"; neither is worth copying. Every
                // other value is valid, including 0, which the engine writes at
                // RVA 0x8C988. Filtering on "greater than zero" cost the move
                // cursor in the 20:25 run.
                if (nativeSelected <= 0 || kind == -10 || kind == -1)
                {
                    return;
                }
                string learned;
                if (hoveredEnemy && _cursorAttackBlock == null)
                {
                    _cursorAttackBlock = current;
                    learned = "enemy";
                }
                else if (plainGround && _cursorMoveBlock == null)
                {
                    _cursorMoveBlock = current;
                    learned = "ground";
                }
                else
                {
                    return;
                }
                if (_cursorSamplesLogged < MaxCursorSamplesLogged)
                {
                    _cursorSamplesLogged++;
                    _info(
                        "Worker militia learned a native command cursor from a"
                        + " regular troop selection: context=" + learned
                        + " kind=" + kind.ToString(CultureInfo.InvariantCulture)
                        + " block=" + DescribeCursorBlock(current)
                        + " move_known="
                        + (_cursorMoveBlock != null).ToString()
                        + " attack_known="
                        + (_cursorAttackBlock != null).ToString() + ".");
                }
                return;
            }

            int[] wanted = hoveredEnemy
                ? _cursorAttackBlock
                : (plainGround ? _cursorMoveBlock : null);
            if (wanted == null || CursorBlocksMatch(current, wanted))
            {
                return;
            }
            WriteCursorBlock(baseAddress, wanted);
            if (_cursorReplaysLogged < MaxCursorReplayLogs)
            {
                _cursorReplaysLogged++;
                _info(
                    "Worker militia replayed the native command cursor for its"
                    + " own worker: was=" + DescribeCursorBlock(current)
                    + " now=" + DescribeCursorBlock(wanted)
                    + " context=" + (hoveredEnemy ? "enemy" : "ground")
                    + " worker_id="
                    + workerId.ToString(CultureInfo.InvariantCulture) + ".");
            }
        }

        private static void FaceTarget(
            int workerId,
            UnitSnapshot worker,
            UnitSnapshot target)
        {
            int dx = target.CombatX - worker.CombatX;
            int dy = target.CombatY - worker.CombatY;
            Dircs direction;
            if (dx == 0 && dy == 0)
            {
                direction = Dircs.Centre;
            }
            else if (Math.Abs(dx) * 2 < Math.Abs(dy))
            {
                direction = dy < 0 ? Dircs.North : Dircs.South;
            }
            else if (Math.Abs(dy) * 2 < Math.Abs(dx))
            {
                direction = dx > 0 ? Dircs.East : Dircs.West;
            }
            else if (dx > 0)
            {
                direction = dy < 0 ? Dircs.NE : Dircs.SE;
            }
            else
            {
                direction = dy < 0 ? Dircs.NW : Dircs.SW;
            }
            GameUnitManagerAPI.Instance.SetDirection(workerId, direction);
        }

        private static void ComputeApproachTile(
            UnitSnapshot worker,
            UnitSnapshot target,
            int attackRange,
            out int destinationX,
            out int destinationY)
        {
            int dx = target.X - worker.X;
            int dy = target.Y - worker.Y;
            double distance = Math.Sqrt((double)dx * dx + (double)dy * dy);
            if (distance <= attackRange || distance <= 0.0)
            {
                destinationX = worker.X;
                destinationY = worker.Y;
                return;
            }
            double stop = Math.Max(1, attackRange);
            destinationX = target.X - (int)Math.Round(dx * stop / distance);
            destinationY = target.Y - (int)Math.Round(dy * stop / distance);
        }

        private bool OutsidePursuit(CommandState command, UnitSnapshot target)
        {
            if (command == null || target == null)
            {
                return true;
            }
            if (!WorkerMilitiaMissionRules.UsesLocalPursuitLeash(
                    command.Manual,
                    command.ExplicitTarget))
            {
                return false;
            }
            int pursuit = PursuitRadius(command.WorkerType);
            return DistanceSquared(
                command.CombatAnchorX,
                command.CombatAnchorY,
                target.CombatX,
                target.CombatY) > (long)pursuit * pursuit;
        }

        private UnitSnapshot FindBestEnemy(
            UnitSnapshot worker,
            UnitSpatialIndex spatialIndex,
            int radius,
            CommandState command,
            int excludedTarget)
        {
            if (worker == null || spatialIndex == null || radius < 0)
            {
                return null;
            }
            long radiusSquared = (long)radius * radius;
            UnitSnapshot best = null;
            int bestPriority = int.MaxValue;
            long bestDistance = long.MaxValue;
            int minimumBucketX = spatialIndex.MinimumBucket(worker.CombatX, radius);
            int maximumBucketX = spatialIndex.MaximumBucket(worker.CombatX, radius);
            int minimumBucketY = spatialIndex.MinimumBucket(worker.CombatY, radius);
            int maximumBucketY = spatialIndex.MaximumBucket(worker.CombatY, radius);
            for (int bucketX = minimumBucketX;
                bucketX <= maximumBucketX;
                bucketX++)
            {
                for (int bucketY = minimumBucketY;
                    bucketY <= maximumBucketY;
                    bucketY++)
                {
                    List<UnitSnapshot> bucket = spatialIndex.GetBucket(
                        bucketX,
                        bucketY);
                    if (bucket == null)
                    {
                        continue;
                    }
                    foreach (UnitSnapshot candidate in bucket)
                    {
                        if (candidate.Id == excludedTarget
                            || !IsEnemyPlayerUnit(
                                worker.Owner,
                                candidate.Owner)
                            || !CanDamage(worker.Type, candidate.Type))
                        {
                            continue;
                        }
                        long distance = DistanceSquared(
                            worker.CombatX,
                            worker.CombatY,
                            candidate.CombatX,
                            candidate.CombatY);
                        if (distance > radiusSquared)
                        {
                            continue;
                        }
                        if (command != null
                            && OutsidePursuit(command, candidate))
                        {
                            continue;
                        }
                        int priority = ThreatPriority(candidate.Type);
                        if (priority < bestPriority
                            || (priority == bestPriority
                                && (distance < bestDistance
                                    || (distance == bestDistance
                                        && (best == null
                                            || candidate.Id < best.Id)))))
                        {
                            best = candidate;
                            bestPriority = priority;
                            bestDistance = distance;
                        }
                    }
                }
            }
            return best;
        }

        private List<UnitSnapshot> CaptureUnits()
        {
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            int[] ids = units.GetAllAliveUnits();
            var snapshots = new List<UnitSnapshot>(ids.Length);
            foreach (int id in ids)
            {
                UnitSnapshot snapshot = CaptureUnit(id);
                if (snapshot != null
                    && snapshot.Owner >= 1
                    && snapshot.Owner <= 8)
                {
                    snapshots.Add(snapshot);
                }
            }
            return snapshots;
        }

        private static UnitSnapshot CaptureUnit(int id)
        {
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (!units.IsValid(id)
                || !units.TryGetUnitByIdEx(id, out var pointer))
            {
                return null;
            }
            ref GameUnit unit = ref pointer.AsRef();
            eChimps type = units.GetType(id);
            // Guard, pursuit and MoveToTile all use the coarse map-tile grid.
            // World coordinates are eight times finer and are only correct for
            // CreateProjectile; using them here silently divided every radius
            // by eight and sent movement orders to the wrong tiles.
            var position = units.GetCurrentLocalTilePosition(id);
            return new UnitSnapshot
            {
                Id = id,
                GlobalId = units.GetGlobalId(id),
                Type = type,
                Owner = units.GetOwner(id),
                X = position.X,
                Y = position.Y,
                // Exact operands of CrusaderDE.dll RVA 0x19A360. The native
                // range operator sign-extends both ushort storage words and
                // divides by eight with truncation toward zero before applying
                // its inclusive Euclidean comparison.
                CombatX = unchecked((short)unit.r_CurrentWorldPositionX)
                    / WorldTilesPerLocalTile,
                CombatY = unchecked((short)unit.r_CurrentWorldPositionY)
                    / WorldTilesPerLocalTile,
                TileId = unit.r_CurrentPositionTileId,
                WorkLink = IsMilitia(type)
                    ? ReadExposedUnitInt(
                        id,
                        "r_LinkedProductionBuildingId")
                    : 0,
                TribeId = IsMilitia(type) ? units.GetTribe(id) : 0,
            };
        }

        /// <summary>
        /// Work link for a log line, or "gone" - telemetry must never be the
        /// reason the feature stops.
        /// </summary>
        private static string DescribeWorkLink(int unitId)
        {
            int workLink;
            return TryReadExposedUnitInt(
                    unitId,
                    "r_LinkedProductionBuildingId",
                    out workLink)
                ? workLink.ToString(CultureInfo.InvariantCulture)
                : "gone";
        }

        /// <summary>
        /// Reads a pinned, Lua-exposed unit field, separating "this unit is
        /// gone" from "this field is not exposed".
        /// </summary>
        /// <remarks>
        /// <c>LuaUnitAPI.GetUnitField</c> returns null for both, and the strict
        /// reader below turned both into an exception. Only the second is a
        /// contract breach. The first is an ordinary combat event - a target
        /// that dies between the scan and the shot - and on the Tick or
        /// run-postfix path an exception there stops the whole feature for the
        /// session. Callers that can meet a vanished unit use this form.
        /// </remarks>
        private static bool TryReadExposedUnitInt(
            int unitId,
            string field,
            out int value)
        {
            value = 0;
            object raw = LuaUnitAPI.GetUnitField(unitId, field);
            if (raw == null)
            {
                GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                if (units == null
                    || !IsPlausibleUnitId(unitId)
                    || !units.IsValid(unitId))
                {
                    return false;
                }
                // The unit is there, so the field really is missing. That is a
                // broken pin and must stay fail-closed.
                throw new InvalidOperationException(
                    "Pinned unit field is not Lua-exposed: " + field);
            }
            value = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
            return true;
        }

        /// <summary>
        /// Strict form, for callers that already hold a validated unit pointer
        /// and for which a vanished unit would itself be a broken invariant.
        /// </summary>
        private static int ReadExposedUnitInt(int unitId, string field)
        {
            int value;
            if (!TryReadExposedUnitInt(unitId, field, out value))
            {
                throw new InvalidOperationException(
                    "Pinned unit field was read for a unit that is gone: "
                    + field);
            }
            return value;
        }

        private static bool TryCaptureWorkerOccupancy(
            int unitId,
            int expectedGlobalId,
            int expectedOwner,
            eChimps expectedType,
            out OccupancyProvenance occupancy)
        {
            occupancy = null;
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
            if (units == null
                || buildings == null
                || unitId <= 0
                || expectedGlobalId <= 0
                || expectedOwner < 1
                || expectedOwner > 8
                || !IsMilitia(expectedType)
                || !units.TryGetUnitByIdEx(unitId, out var unitPointer))
            {
                return false;
            }
            ref GameUnit unit = ref unitPointer.AsRef();
            if (unit.r_AliveState != AliveState.IsAlive
                || unchecked((int)unit.r_GlobalId) != expectedGlobalId
                || unit.r_ControllableForPlayerId != expectedOwner
                || unit.r_UnitChimp != expectedType)
            {
                return false;
            }

            // These are exact, read-only projections of Unit+0x392 and
            // Unit+0x394. Prepare pins both containing fields and their split
            // offsets before this code can run.
            int slotIndex = unchecked((int)(unit.N000000C5 >> 16));
            int buildingId = unchecked((int)(unit.N000001D8 & ushort.MaxValue));
            if (slotIndex < 0
                || slotIndex >= NativeWorkerSlotCount
                || buildingId <= 0
                || buildingId > ushort.MaxValue
                || !buildings.TryGetBuildingByIdEx(
                    buildingId,
                    out var buildingPointer))
            {
                return false;
            }
            ref GameBuilding building = ref buildingPointer.AsRef();
            int requiredWorkers = building.r_TotalWorkersRequired;
            int buildingGlobalId = unchecked((int)building.r_GlobalId);
            if (building.r_AliveState != AliveState.IsAlive
                || buildingGlobalId <= 0
                || !Enum.IsDefined(
                    typeof(eStructs),
                    building.r_BuildingType)
                || building.r_PlayerIdOwner != expectedOwner
                || requiredWorkers < 1
                || requiredWorkers > NativeWorkerSlotCount
                || slotIndex >= requiredWorkers
                || ReadBuildingWorkerId(ref building, slotIndex) != unitId
                || ReadBuildingWorkerGlobalId(ref building, slotIndex)
                    != expectedGlobalId)
            {
                return false;
            }
            occupancy = new OccupancyProvenance
            {
                SlotIndex = slotIndex,
                BuildingId = buildingId,
                BuildingGlobalId = buildingGlobalId,
                BuildingType = building.r_BuildingType,
                BuildingOwner = building.r_PlayerIdOwner,
                RequiredWorkers = requiredWorkers,
            };
            return true;
        }

        private static bool WorkerOccupancyMatches(
            int unitId,
            int expectedGlobalId,
            int expectedOwner,
            eChimps expectedType,
            OccupancyProvenance expected)
        {
            OccupancyProvenance live;
            return expected != null
                && TryCaptureWorkerOccupancy(
                    unitId,
                    expectedGlobalId,
                    expectedOwner,
                    expectedType,
                    out live)
                && OccupancyProvenanceMatches(expected, live);
        }

        private static bool OccupancyProvenanceMatches(
            OccupancyProvenance expected,
            OccupancyProvenance live)
        {
            return expected != null
                && live != null
                && live.SlotIndex == expected.SlotIndex
                && live.BuildingId == expected.BuildingId
                && live.BuildingGlobalId == expected.BuildingGlobalId
                && live.BuildingType == expected.BuildingType
                && live.BuildingOwner == expected.BuildingOwner
                && live.RequiredWorkers == expected.RequiredWorkers;
        }

        private static OccupancyProvenance CopyOccupancy(
            OccupancyProvenance source)
        {
            if (source == null)
            {
                return null;
            }
            return new OccupancyProvenance
            {
                SlotIndex = source.SlotIndex,
                BuildingId = source.BuildingId,
                BuildingGlobalId = source.BuildingGlobalId,
                BuildingType = source.BuildingType,
                BuildingOwner = source.BuildingOwner,
                RequiredWorkers = source.RequiredWorkers,
            };
        }

        private static int ReadBuildingWorkerId(
            ref GameBuilding building,
            int slotIndex)
        {
            switch (slotIndex)
            {
                case 0:
                    return building.r_WorkerId_1;
                case 1:
                    return building.r_WorkerId_2;
                case 2:
                    return building.r_WorkerId_3;
                case 3:
                    return unchecked(
                        (int)(building.r_WorkerId_4 & ushort.MaxValue));
                default:
                    return -1;
            }
        }

        private static int ReadBuildingWorkerGlobalId(
            ref GameBuilding building,
            int slotIndex)
        {
            switch (slotIndex)
            {
                case 0:
                    return unchecked((int)building.N0000176A);
                case 1:
                    return unchecked((int)building.N000017F1);
                case 2:
                    return unchecked((int)building.N0000176B);
                case 3:
                    return unchecked((int)building.N000017F3);
                default:
                    return -1;
            }
        }

        private void LogScanCensus(
            List<UnitSnapshot> snapshots,
            UnitSpatialIndex spatialIndex,
            int now)
        {
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            int localPlayer = players.GetLocalPlayerId();
            int hunters = 0;
            int woodcutters = 0;
            int workersInTribe = 0;
            int enemyPairs = 0;
            int undamageableEnemyPairs = 0;
            int enemyUnits = 0;
            int hunterDamageableEnemyUnits = 0;
            int woodcutterDamageableEnemyUnits = 0;
            long nearestHunter = long.MaxValue;
            long nearestWoodcutter = long.MaxValue;
            foreach (UnitSnapshot candidate in snapshots)
            {
                if (!IsEnemyPlayerUnit(localPlayer, candidate.Owner))
                {
                    continue;
                }
                enemyUnits++;
                if (CanDamage(eChimps.CHIMP_TYPE_HUNTER, candidate.Type))
                {
                    hunterDamageableEnemyUnits++;
                }
                if (CanDamage(eChimps.CHIMP_TYPE_WOODCUTTER, candidate.Type))
                {
                    woodcutterDamageableEnemyUnits++;
                }
            }
            foreach (UnitSnapshot worker in snapshots)
            {
                if (worker.Owner != localPlayer || !IsMilitia(worker.Type))
                {
                    continue;
                }
                if (worker.Type == eChimps.CHIMP_TYPE_HUNTER)
                {
                    hunters++;
                }
                else
                {
                    woodcutters++;
                }
                if (worker.TribeId != 0)
                {
                    workersInTribe++;
                }
                int radius = GuardRadius(worker.Type);
                long radiusSquared = (long)radius * radius;
                int minimumBucketX = spatialIndex.MinimumBucket(
                    worker.CombatX,
                    radius);
                int maximumBucketX = spatialIndex.MaximumBucket(
                    worker.CombatX,
                    radius);
                int minimumBucketY = spatialIndex.MinimumBucket(
                    worker.CombatY,
                    radius);
                int maximumBucketY = spatialIndex.MaximumBucket(
                    worker.CombatY,
                    radius);
                for (int bucketX = minimumBucketX;
                    bucketX <= maximumBucketX;
                    bucketX++)
                {
                    for (int bucketY = minimumBucketY;
                        bucketY <= maximumBucketY;
                        bucketY++)
                    {
                        List<UnitSnapshot> bucket = spatialIndex.GetBucket(
                            bucketX,
                            bucketY);
                        if (bucket == null)
                        {
                            continue;
                        }
                        foreach (UnitSnapshot candidate in bucket)
                        {
                            if (!IsEnemyPlayerUnit(
                                    worker.Owner,
                                    candidate.Owner))
                            {
                                continue;
                            }
                            long distance = DistanceSquared(
                                worker.CombatX,
                                worker.CombatY,
                                candidate.CombatX,
                                candidate.CombatY);
                            if (distance > radiusSquared)
                            {
                                continue;
                            }
                            if (!CanDamage(worker.Type, candidate.Type))
                            {
                                undamageableEnemyPairs++;
                                continue;
                            }
                            enemyPairs++;
                            if (worker.Type == eChimps.CHIMP_TYPE_HUNTER)
                            {
                                nearestHunter = Math.Min(
                                    nearestHunter,
                                    distance);
                            }
                            else
                            {
                                nearestWoodcutter = Math.Min(
                                    nearestWoodcutter,
                                    distance);
                            }
                        }
                    }
                }
            }
            if (hunters == 0 && woodcutters == 0)
            {
                return;
            }
            bool first = !_scanCensusLogged;
            bool hadContact = _lastScanEnemyPairs > 0;
            bool hasContact = enemyPairs > 0;
            bool contactChanged = !first && hadContact != hasContact;
            bool heartbeat = hasContact
                && HasReached(now, _nextScanCensusLogTick);
            _lastScanEnemyPairs = enemyPairs;
            if (!first && !contactChanged && !heartbeat)
            {
                return;
            }
            string reason = first
                ? "first"
                : contactChanged
                    ? (hasContact ? "contact_started" : "contact_cleared")
                    : "contact_heartbeat";
            _scanCensusLogged = true;
            _nextScanCensusLogTick = unchecked(
                now + ScanCensusHeartbeatMilliseconds);
            _info(
                "Worker militia scan: reason=" + reason + " local_player="
                + localPlayer.ToString(CultureInfo.InvariantCulture)
                + " local_team="
                + players.GetPlayerTeam(localPlayer).ToString(
                    CultureInfo.InvariantCulture)
                + " hunters=" + hunters.ToString(CultureInfo.InvariantCulture)
                + " woodcutters="
                + woodcutters.ToString(CultureInfo.InvariantCulture)
                + " workers_in_tribe="
                + workersInTribe.ToString(CultureInfo.InvariantCulture)
                + " active_commands="
                + _commands.Count.ToString(CultureInfo.InvariantCulture)
                + " enemy_units="
                + enemyUnits.ToString(CultureInfo.InvariantCulture)
                + " hunter_damageable_enemies="
                + hunterDamageableEnemyUnits.ToString(
                    CultureInfo.InvariantCulture)
                + " woodcutter_damageable_enemies="
                + woodcutterDamageableEnemyUnits.ToString(
                    CultureInfo.InvariantCulture)
                + " enemy_pairs="
                + enemyPairs.ToString(CultureInfo.InvariantCulture)
                + " undamageable_enemy_pairs="
                + undamageableEnemyPairs.ToString(CultureInfo.InvariantCulture)
                + " hunter_range_calibrated="
                + TelemetryBoolean(
                    GeneratedWorkerMilitiaContract.HunterRangeCalibrated)
                + " nearest_hunter_tiles=" + DistanceText(nearestHunter)
                + " nearest_woodcutter_tiles="
                + DistanceText(nearestWoodcutter) + ".");
        }

        private static string DistanceText(long squared)
        {
            return squared == long.MaxValue
                ? "none"
                : Math.Sqrt(squared).ToString("0.0", CultureInfo.InvariantCulture);
        }

        private void ApplyWoodcutterRow()
        {
            if (_woodcutterRow != null)
            {
                // Schon angelegt: idempotent aussteigen. OnStartMap ruft das
                // auf, und ein Wurf dort nimmt den Mod beim Kartenstart mit.
                return;
            }
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            var maceman = new int[ValidTargetCount];
            for (int target = 0; target < maceman.Length; target++)
            {
                maceman[target] = units.GetMeleeDamageFromTo(
                    eChimps.CHIMP_TYPE_MACEMAN,
                    (eChimps)target);
            }
            // Diese Methode laeuft aus OnStartMap. Ein Wurf hier landet im
            // Sammelfang des Kartenstarts und schaltet die Miliz fuer die
            // ganze Partie ab - wegen einer Zugabe, ohne die der Holzfaeller
            // weiter arbeitet und befehligbar bleibt. Nur sein Nahkampfschlag
            // faellt aus.
            int[] weak;
            try
            {
                weak = WorkerMilitiaDamagePlan.FromMacemanRow(
                    maceman,
                    GeneratedWorkerMilitiaContract.DamageDivisor);
            }
            catch (Exception exception)
            {
                if (_evidenceLogged.Add("woodcutter_damage_row_unusable"))
                {
                    _warning(
                        "Worker militia could not derive a woodcutter damage "
                        + "row from the maceman row ("
                        + exception.GetType().Name + ": " + exception.Message
                        + "). Woodcutters keep working and stay commandable; "
                        + "only their melee strike is unavailable.");
                }
                return;
            }
            _woodcutterRow = new OwnedStackRowMutation<int>(
                WoodcutterDamageClaim,
                target => units.GetMeleeDamageFromTo(
                    eChimps.CHIMP_TYPE_WOODCUTTER,
                    (eChimps)target),
                (target, value) => LuaUnitAPI.PushMeleeDamageFromTo(
                    eChimps.CHIMP_TYPE_WOODCUTTER,
                    (eChimps)target,
                    value),
                target => LuaUnitAPI.PopMeleeDamageFromTo(
                    eChimps.CHIMP_TYPE_WOODCUTTER,
                    (eChimps)target),
                weak);
            string failure;
            if (!_woodcutterRow.TryApply(out failure))
            {
                _woodcutterRow = null;
                if (_evidenceLogged.Add("woodcutter_row_refused"))
                {
                    _warning(
                        "Worker militia could not install the woodcutter melee "
                        + "row: " + failure + ". Woodcutters keep working and "
                        + "stay commandable; only their melee strike is "
                        + "unavailable.");
                }
                return;
            }
        }

        private void ApplyHunterHutAvailability()
        {
            if (_hunterHutAvailability != null)
            {
                return;
            }
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            _hunterHutAvailability = new OwnedValueMutation<bool>(
                HunterHutAvailabilityClaim,
                () => players.GetBuildingAvailability(eMappers.MAPPER_HUNTER),
                value => players.SetBuildingAvailability(
                    eMappers.MAPPER_HUNTER,
                    value),
                true);
            string failure;
            if (!_hunterHutAvailability.TryApply(out failure))
            {
                _hunterHutAvailability = null;
                if (_evidenceLogged.Add("hunter_hut_availability_refused"))
                {
                    _warning(
                        "Worker militia could not enable the hunter hut in the "
                        + "build menu: " + failure + ". Existing hunters are "
                        + "unaffected; only the new-build entry is missing.");
                }
                return;
            }
            if (!players.GetBuildingAvailability(eMappers.MAPPER_HUNTER))
            {
                _hunterHutAvailability = null;
                if (_evidenceLogged.Add("hunter_hut_availability_readback"))
                {
                    _warning(
                        "Worker militia read back a disabled hunter hut after "
                        + "enabling it; the build-menu entry is given up and "
                        + "the militia continues without it.");
                }
                return;
            }
            _info(
                "Worker militia hunter hut enabled in the farm build menu: "
                + "mapper=78 readback=true; can-place override armed; "
                + "HUD refresh enqueued by the Extender.");
        }

        private void RollbackHunterHutAvailability(string reason)
        {
            OwnedValueMutation<bool> mutation = _hunterHutAvailability;
            _hunterHutAvailability = null;
            if (mutation == null)
            {
                return;
            }
            string failure;
            OwnedRollbackOutcome outcome = mutation.RollbackOwned(out failure);
            if (outcome == OwnedRollbackOutcome.OwnershipLost)
            {
                _warning(
                    "Worker militia hunter-hut availability lost ownership during "
                    + reason + "; the foreign value was preserved.");
            }
            else if (outcome == OwnedRollbackOutcome.Failed)
            {
                throw new InvalidOperationException(
                    "Hunter-hut availability rollback failed during " + reason
                    + ": " + failure);
            }
        }

        private void RollbackWoodcutterRow(string reason)
        {
            OwnedStackRowMutation<int> row = _woodcutterRow;
            _woodcutterRow = null;
            if (row == null)
            {
                return;
            }
            StackRowRollbackSummary summary;
            string failure;
            bool succeeded = row.RollbackOwned(out summary, out failure);
            if (summary.OwnershipLost > 0)
            {
                _warning(
                    "Worker militia woodcutter row lost ownership of "
                    + summary.OwnershipLost.ToString(CultureInfo.InvariantCulture)
                    + " cells during " + reason + "; foreign values were preserved.");
            }
            if (!succeeded)
            {
                throw new InvalidOperationException(
                    "Woodcutter melee row rollback failed during " + reason
                    + ": " + failure);
            }
        }

        private void ReturnAllToWork(string reason, bool issueMove)
        {
            var commands = new List<CommandState>(_commands.Values);
            foreach (CommandState command in commands)
            {
                QueueCommandForNativeBoundary(command, reason);
            }
            if (issueMove && commands.Count > 0)
            {
                _info(
                    "Worker militia cleanup queued preserved work handoff at "
                    + "the native run boundary during " + reason
                    + "; return_move=false.");
            }
        }

        private void ReturnAllOtherCommandsToWork(
            int quarantinedWorkerId,
            string reason,
            bool issueMove)
        {
            var commands = new List<CommandState>();
            foreach (CommandState command in _commands.Values)
            {
                if (command.WorkerUnitId != quarantinedWorkerId)
                {
                    commands.Add(command);
                }
            }
            foreach (CommandState command in commands)
            {
                QueueCommandForNativeBoundary(command, reason);
            }
            if (issueMove && commands.Count > 0)
            {
                _info(
                    "Worker militia isolated cleanup queued preserved work "
                    + "handoff at the native run boundary during " + reason
                    + "; return_move=false.");
            }
        }

        private void QueueCommandForNativeBoundary(
            CommandState command,
            string reason)
        {
            if (command == null)
            {
                return;
            }
            PendingDirectWorkCompletion pending;
            if (_pendingDirectWorkCompletions.TryGetValue(
                    command.WorkerUnitId,
                    out pending))
            {
                if (!ReferenceEquals(pending.Command, command))
                {
                    if (_evidenceLogged.Add("cleanup_foreign_pending_owner"))
                    {
                        _warning(
                            "Worker militia cleanup encountered a foreign "
                            + "pending direct-work owner; the foreign entry is "
                            + "left untouched.");
                    }
                }
                return;
            }
            NoteWorkplaceLoss(command);
            UnitSnapshot worker = CaptureUnit(command.WorkerUnitId);
            if (worker == null
                || worker.GlobalId != command.WorkerGlobalId
                || worker.Type != command.WorkerType
                || worker.Owner != command.WorkerOwner)
            {
                _commands.Remove(command.WorkerUnitId);
                command.DirectWorkCompletionPending = false;
                command.OwnsCommandMode = false;
                _warning(
                    "Worker militia cleanup discarded a stale command without "
                    + "touching its reused/native unit slot.");
                return;
            }
            CompleteDirectWork(
                command,
                worker,
                reason,
                false,
                false);
        }

        private static SavedCommand CreateSavedCommand(
            CommandState command,
            int now)
        {
            bool pendingDirectWork = command.DirectWorkCompletionPending
                && command.Phase == MissionPhase.DirectWorkPending;
            MissionPhase savedPhase = pendingDirectWork
                ? command.DirectWorkSnapshotPhase
                : command.Phase;
            int savedTargetGlobalId = pendingDirectWork
                ? command.DirectWorkSnapshotTargetGlobalId
                : (command.TargetUnitId > 0 ? command.TargetGlobalId : 0);
            if (savedPhase != MissionPhase.Fighting)
            {
                savedTargetGlobalId = 0;
            }
            else if (savedTargetGlobalId <= 0
                || savedTargetGlobalId == command.WorkerGlobalId)
            {
                savedTargetGlobalId = UnresolvedSavedTargetGlobalId;
            }
            bool savedExplicitTarget = pendingDirectWork
                ? command.DirectWorkSnapshotExplicitTarget
                : command.ExplicitTarget;
            int savedHoldRemainingMilliseconds = savedPhase
                    == MissionPhase.Holding
                ? (pendingDirectWork
                    ? command.DirectWorkSnapshotHoldRemainingMilliseconds
                    : RemainingMilliseconds(
                        now,
                        command.HoldDeadlineTick,
                        GeneratedWorkerMilitiaContract.HoldDurationMilliseconds))
                : 0;
            return new SavedCommand
            {
                CommandGeneration = command.Generation,
                WorkerUnitId = command.WorkerUnitId,
                WorkerGlobalId = command.WorkerGlobalId,
                WorkerType = command.WorkerType,
                Owner = command.WorkerOwner,
                TargetGlobalId = savedTargetGlobalId,
                OriginX = command.OriginX,
                OriginY = command.OriginY,
                OriginalWorkLink = command.OriginalWorkLink,
                OriginalTribeId = command.OriginalTribeId,
                Manual = command.Manual,
                ExplicitTarget = savedExplicitTarget,
                Phase = savedPhase,
                HasManualDestination = command.HasManualDestination,
                ManualDestinationReached = command.ManualDestinationReached,
                ManualDestinationX = command.ManualDestinationX,
                ManualDestinationY = command.ManualDestinationY,
                CombatAnchorX = command.CombatAnchorX,
                CombatAnchorY = command.CombatAnchorY,
                DamageObserved = command.DamageObserved,
                HoldRemainingMilliseconds = savedHoldRemainingMilliseconds,
                OriginalCommandModeValue = command.OriginalCommandModeValue,
                WorkplaceLost = command.WorkplaceLost,
                ResumeHoldAfterCombat = command.ResumeHoldAfterCombat,
                PausedHoldRemainingMilliseconds =
                    command.PausedHoldRemainingMilliseconds,
                NextAttackRemainingMilliseconds = RemainingMilliseconds(
                    now,
                    command.NextAttackTick,
                    AttackCooldown(command.WorkerType)),
                NextMoveRemainingMilliseconds = RemainingMilliseconds(
                    now,
                    command.NextMoveTick,
                    GeneratedWorkerMilitiaContract.MoveRefreshMilliseconds),
                HasIssuedMove = command.HasIssuedMove,
                IssuedMoveX = command.IssuedMoveX,
                IssuedMoveY = command.IssuedMoveY,
                LastProgressX = command.LastProgressX,
                LastProgressY = command.LastProgressY,
                MoveStallRemainingMilliseconds = command.HasIssuedMove
                    ? RemainingMilliseconds(
                        now,
                        unchecked(
                            command.LastProgressTick + MoveStallMilliseconds),
                        MoveStallMilliseconds)
                    : 0,
                StallWindowElapsedMilliseconds = command.HasIssuedMove
                    ? ElapsedMilliseconds(
                        now,
                        command.StallWindowStartTick,
                        ManualMoveAbortMilliseconds)
                    : 0,
                StallRetryCount = command.HasIssuedMove
                    ? Math.Min(
                        ManualMoveAbortRetryFloor,
                        Math.Max(0, command.StallRetryCount))
                    : 0,
                Occupancy = CopyOccupancy(command.Occupancy),
            };
        }

        private static bool IsValidSavedCommand(
            SavedCommand saved,
            bool requireVersion4State = true)
        {
            if (saved == null
                || (requireVersion4State
                    && (saved.CommandGeneration <= 0
                        || saved.CommandGeneration == long.MaxValue
                        || !IsPlausibleUnitId(saved.WorkerUnitId)))
                || saved.WorkerGlobalId <= 0
                || !IsMilitia(saved.WorkerType)
                || saved.Owner < 1 || saved.Owner > 8
                || (saved.TargetGlobalId < 0
                    && saved.TargetGlobalId != UnresolvedSavedTargetGlobalId)
                || saved.TargetGlobalId == saved.WorkerGlobalId
                || saved.OriginalWorkLink < 0
                || saved.OriginalWorkLink > ushort.MaxValue
                || saved.OriginalTribeId < 0
                || saved.OriginalTribeId > ushort.MaxValue
                || !IsValidSavedOccupancy(saved.Occupancy, saved.Owner)
                || saved.HoldRemainingMilliseconds < 0
                || saved.HoldRemainingMilliseconds
                    > GeneratedWorkerMilitiaContract.HoldDurationMilliseconds
                || saved.OriginalCommandModeValue != 0
                || saved.PausedHoldRemainingMilliseconds < 0
                || saved.PausedHoldRemainingMilliseconds
                    > GeneratedWorkerMilitiaContract.HoldDurationMilliseconds
                || (requireVersion4State
                    && (saved.NextAttackRemainingMilliseconds < 0
                        || saved.NextAttackRemainingMilliseconds
                            > AttackCooldown(saved.WorkerType)
                        || saved.NextMoveRemainingMilliseconds < 0
                        || saved.NextMoveRemainingMilliseconds
                            > GeneratedWorkerMilitiaContract.MoveRefreshMilliseconds
                        || saved.MoveStallRemainingMilliseconds < 0
                        || saved.MoveStallRemainingMilliseconds
                            > MoveStallMilliseconds
                        || saved.StallWindowElapsedMilliseconds < 0
                        || saved.StallWindowElapsedMilliseconds
                            > ManualMoveAbortMilliseconds
                        || saved.StallRetryCount < 0
                        || saved.StallRetryCount
                            > ManualMoveAbortRetryFloor
                        || (!saved.Manual && saved.StallRetryCount != 0)
                        || !IsValidMapTile(
                            saved.LastProgressX,
                            saved.LastProgressY)
                        || (saved.HasIssuedMove
                            && !IsValidMapTile(
                                saved.IssuedMoveX,
                                saved.IssuedMoveY))
                        || (!saved.HasIssuedMove
                            && (saved.MoveStallRemainingMilliseconds != 0
                                || saved.StallWindowElapsedMilliseconds != 0
                                || saved.StallRetryCount != 0))))
                || !IsValidMapTile(saved.OriginX, saved.OriginY)
                || !IsValidMapTile(
                    saved.ManualDestinationX,
                    saved.ManualDestinationY)
                || !IsValidMapTile(
                    saved.CombatAnchorX,
                    saved.CombatAnchorY))
            {
                return false;
            }
            if (saved.Phase == MissionPhase.Outbound)
            {
                return saved.Manual
                    && !saved.ExplicitTarget
                    && saved.TargetGlobalId == 0
                    && saved.HasManualDestination
                    && !saved.ManualDestinationReached
                    && saved.HoldRemainingMilliseconds == 0;
            }
            if (saved.Phase == MissionPhase.Fighting)
            {
                return (saved.TargetGlobalId > 0
                        || saved.TargetGlobalId
                            == UnresolvedSavedTargetGlobalId)
                    && (!saved.ExplicitTarget || saved.Manual)
                    && (!saved.HasManualDestination || saved.Manual)
                    && (!saved.ManualDestinationReached
                        || saved.HasManualDestination)
                    && saved.HoldRemainingMilliseconds == 0
                    && (!saved.ResumeHoldAfterCombat
                        || (saved.Manual
                            && !saved.ExplicitTarget
                            && saved.HasManualDestination
                            && saved.ManualDestinationReached
                            && saved.PausedHoldRemainingMilliseconds > 0));
            }
            return saved.Phase == MissionPhase.Holding
                && saved.TargetGlobalId == 0
                && !saved.ExplicitTarget
                && saved.Manual
                && saved.HasManualDestination
                && saved.ManualDestinationReached
                && !saved.ResumeHoldAfterCombat
                && saved.PausedHoldRemainingMilliseconds == 0;
        }

        private static SavedOwnedProjectile CreateSavedOwnedProjectile(
            OwnedProjectile projectile,
            int now)
        {
            return new SavedOwnedProjectile
            {
                ProjectileId = projectile.ProjectileId,
                MilitiaGeneration = projectile.MilitiaGeneration,
                WorkerUnitId = projectile.WorkerUnitId,
                WorkerGlobalId = projectile.WorkerGlobalId,
                WorkerOwner = projectile.WorkerOwner,
                WorkerType = projectile.WorkerType,
                TargetUnitId = projectile.TargetUnitId,
                TargetGlobalId = projectile.TargetGlobalId,
                ReferenceDamage = projectile.ReferenceDamage,
                RemainingLifetimeMilliseconds = RemainingMilliseconds(
                    now,
                    projectile.DeadlineTick,
                    OwnedProjectileLifetimeMilliseconds),
            };
        }

        private static bool IsValidSavedOwnedProjectile(
            SavedOwnedProjectile saved)
        {
            return saved != null
                && saved.ProjectileId > 0
                && saved.MilitiaGeneration > 0
                && saved.MilitiaGeneration < long.MaxValue
                && IsPlausibleUnitId(saved.WorkerUnitId)
                && saved.WorkerGlobalId > 0
                && saved.WorkerOwner >= 1
                && saved.WorkerOwner <= 8
                && IsMilitia(saved.WorkerType)
                && IsPlausibleUnitId(saved.TargetUnitId)
                && saved.TargetGlobalId > 0
                && saved.TargetGlobalId != saved.WorkerGlobalId
                && saved.ReferenceDamage >= 0
                && saved.RemainingLifetimeMilliseconds > 0
                && saved.RemainingLifetimeMilliseconds
                    <= OwnedProjectileLifetimeMilliseconds;
        }

        private SavedSelection DeclineSavedSelection(string reason)
        {
            if (_evidenceLogged.Add("save_selection_declined"))
            {
                _warning(
                    "Worker militia saved this game without its worker "
                    + "selection because " + reason
                    + ". Running missions are still saved; on load the worker "
                    + "is simply not preselected.");
            }
            return null;
        }

        private SavedSelection CreateSavedSelection()
        {
            NativeSelectionLease lease = _selectionLease;
            if (lease == null)
            {
                return null;
            }
            if (_nativeSelectionLifecycle != NativeSelectionLifecycle.Confirmed
                || _pendingSelectionWorkerId > 0
                || _selectedWorkerId != lease.UnitId
                || lease.TemporarilySuppressed
                || !IsNativeSingletonSelection(lease.UnitId)
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    lease.UnitId,
                    out var pointer))
            {
                return DeclineSavedSelection(
                    "the selection is not in a stable, confirmed state");
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (!SelectionLeaseMatches(lease, ref unit)
                || SeInteropFieldAliases.CommandMode(ref unit) != 1
                || unit.r_UnitHover == 0
                || unit.r_UnitSelected != lease.Owner
                || ReadExposedUnitInt(
                    lease.UnitId,
                    "r_LinkedProductionBuildingId") != lease.OriginalWorkLink
                || !TribeProvenanceMatches(
                    lease.UnitId,
                    lease.OriginalTribeId,
                    out _))
            {
                return DeclineSavedSelection(
                    "the selection's work/tribe provenance changed");
            }
            var saved = new SavedSelection
            {
                LeaseGeneration = lease.Generation,
                UnitId = lease.UnitId,
                GlobalId = lease.GlobalId,
                Type = lease.Type,
                Owner = lease.Owner,
                OriginalCommandModeValue = lease.OriginalCommandModeValue,
                OriginalSelectionOwnerValue =
                    lease.OriginalSelectionOwnerValue,
                OriginalWorkLink = lease.OriginalWorkLink,
                OriginalTribeId = lease.OriginalTribeId,
                OriginalX = lease.OriginalX,
                OriginalY = lease.OriginalY,
                Occupancy = CopyOccupancy(lease.Occupancy),
            };
            if (!IsValidSavedSelection(saved, true))
            {
                return DeclineSavedSelection(
                    "the selection's provenance is outside the persistable "
                    + "bounds");
            }
            return saved;
        }

        private static bool IsValidSavedSelection(
            SavedSelection saved,
            bool requireLeaseGeneration = false)
        {
            return saved != null
                && (!requireLeaseGeneration
                    || (saved.LeaseGeneration > 0
                        && saved.LeaseGeneration < long.MaxValue
                        && IsPlausibleUnitId(saved.UnitId)))
                && saved.GlobalId > 0
                && IsMilitia(saved.Type)
                && saved.Owner >= 1 && saved.Owner <= 8
                && saved.OriginalCommandModeValue == 0
                && saved.OriginalSelectionOwnerValue == 0
                && saved.OriginalWorkLink >= 0
                && saved.OriginalWorkLink <= ushort.MaxValue
                && saved.OriginalTribeId >= 0
                && saved.OriginalTribeId <= ushort.MaxValue
                && IsValidSavedOccupancy(saved.Occupancy, saved.Owner)
                && IsValidMapTile(saved.OriginalX, saved.OriginalY);
        }

        private static bool IsValidSavedOccupancy(
            OccupancyProvenance occupancy,
            int workerOwner)
        {
            return occupancy != null
                && occupancy.SlotIndex >= 0
                && occupancy.SlotIndex < NativeWorkerSlotCount
                && occupancy.BuildingId > 0
                && occupancy.BuildingId <= ushort.MaxValue
                && occupancy.BuildingGlobalId > 0
                && Enum.IsDefined(
                    typeof(eStructs),
                    occupancy.BuildingType)
                && occupancy.BuildingOwner == workerOwner
                && occupancy.BuildingOwner >= 1
                && occupancy.BuildingOwner <= 8
                && occupancy.RequiredWorkers >= 1
                && occupancy.RequiredWorkers <= NativeWorkerSlotCount
                && occupancy.SlotIndex < occupancy.RequiredWorkers;
        }

        private byte[] SaveMilitiaData(SaveContext context)
        {
            lock (_gate)
            {
                if (context == null || !context.IsSaveFile || !_mapApplied
                    || _networkSuppressed
                    || _selectionQuarantineSuppressed)
                {
                    return null;
                }
                using (var stream = new MemoryStream())
                using (var writer = new BinaryWriter(stream))
                {
                    writer.Write(SaveMagic);
                    writer.Write(SaveVersion);
                    // _gate is the linearization point shared with the native
                    // run postfix. If Save wins, CreateSavedCommand projects a
                    // pending handoff back to its immutable last active phase;
                    // if the postfix wins, the settled command is already gone.
                    SavedSelection savedSelection = CreateSavedSelection();
                    writer.Write(savedSelection != null);
                    if (savedSelection != null)
                    {
                        writer.Write(savedSelection.GlobalId);
                        writer.Write((int)savedSelection.Type);
                        writer.Write(savedSelection.Owner);
                        writer.Write(savedSelection.OriginalCommandModeValue);
                        writer.Write(savedSelection.OriginalSelectionOwnerValue);
                        writer.Write(savedSelection.OriginalWorkLink);
                        writer.Write(savedSelection.OriginalTribeId);
                        writer.Write(savedSelection.OriginalX);
                        writer.Write(savedSelection.OriginalY);
                        writer.Write(savedSelection.Occupancy.SlotIndex);
                        writer.Write(savedSelection.Occupancy.BuildingId);
                        writer.Write(savedSelection.Occupancy.BuildingGlobalId);
                        writer.Write((int)savedSelection.Occupancy.BuildingType);
                        writer.Write(savedSelection.Occupancy.BuildingOwner);
                        writer.Write(savedSelection.Occupancy.RequiredWorkers);
                        writer.Write(savedSelection.UnitId);
                        writer.Write(savedSelection.LeaseGeneration);
                    }
                    var commands = new List<CommandState>(_commands.Values);
                    commands.Sort(
                        (left, right) => left.WorkerGlobalId.CompareTo(
                            right.WorkerGlobalId));
                    if (commands.Count > MaxSavedCommands)
                    {
                        _warning(
                            "Worker militia save contains more live missions "
                            + "than its bounded format can carry; only the "
                            + "first " + MaxSavedCommands.ToString(
                                CultureInfo.InvariantCulture)
                            + " stable global identities are persisted.");
                        commands.RemoveRange(
                            MaxSavedCommands,
                            commands.Count - MaxSavedCommands);
                    }
                    // Filtered before the count is written. A single mission
                    // that cannot be persisted used to throw, and because the
                    // Script Extender catches every exception of the save
                    // callback and then drops the file, one burnt-down
                    // workshop silently cost the player the entire militia
                    // state of that save. Skipping the one mission is the
                    // whole loss now, and it is reported.
                    int saveTick = SimulationNowMilliseconds();
                    var persistable = new List<SavedCommand>();
                    foreach (CommandState command in commands)
                    {
                        NoteWorkplaceLoss(command);
                        UnitSnapshot worker = CaptureUnit(command.WorkerUnitId);
                        if (worker == null
                            || worker.GlobalId != command.WorkerGlobalId
                            || worker.Type != command.WorkerType
                            || worker.Owner != command.WorkerOwner
                            || !CommandMatchesLiveWorkerProvenance(
                                command,
                                command.WorkerUnitId))
                        {
                            _warning(
                                "Worker militia left one mission out of this "
                                + "save because the worker's provenance changed "
                                + "(unit_id="
                                + command.WorkerUnitId.ToString(
                                    CultureInfo.InvariantCulture)
                                + "). Every other mission is saved.");
                            continue;
                        }
                        if (command.Homeless)
                        {
                            // Ohne Arbeitsplatz gibt es keine
                            // Beschaeftigungsherkunft, gegen die ein
                            // Wiederherstellen sich pruefen liesse. Der
                            // Arbeiter ist ohnehin auf dem Weg zum Bergfried;
                            // steht beim Laden noch ein Gegner daneben, bildet
                            // sich der Einsatz von selbst neu.
                            if (_evidenceLogged.Add("save_skips_homeless"))
                            {
                                _info(
                                    "Worker militia left a homeless worker's "
                                    + "mission out of the save; it re-forms by "
                                    + "itself if an enemy is still nearby "
                                    + "after loading.");
                            }
                            continue;
                        }
                        SavedCommand candidate =
                            CreateSavedCommand(command, saveTick);
                        if (!IsValidSavedCommand(candidate))
                        {
                            _warning(
                                "Worker militia left one mission out of this "
                                + "save because its state is outside the "
                                + "persistable bounds (unit_id="
                                + command.WorkerUnitId.ToString(
                                    CultureInfo.InvariantCulture)
                                + "). Every other mission is saved.");
                            continue;
                        }
                        persistable.Add(candidate);
                    }
                    writer.Write(persistable.Count);
                    foreach (SavedCommand saved in persistable)
                    {
                        writer.Write(saved.WorkerGlobalId);
                        writer.Write((int)saved.WorkerType);
                        writer.Write(saved.Owner);
                        writer.Write(saved.TargetGlobalId);
                        writer.Write(saved.OriginX);
                        writer.Write(saved.OriginY);
                        writer.Write(saved.OriginalWorkLink);
                        writer.Write(saved.OriginalTribeId);
                        writer.Write(saved.Manual);
                        writer.Write(saved.ExplicitTarget);
                        writer.Write((byte)saved.Phase);
                        writer.Write(saved.HasManualDestination);
                        writer.Write(saved.ManualDestinationReached);
                        writer.Write(saved.ManualDestinationX);
                        writer.Write(saved.ManualDestinationY);
                        writer.Write(saved.CombatAnchorX);
                        writer.Write(saved.CombatAnchorY);
                        writer.Write(saved.DamageObserved);
                        writer.Write(saved.HoldRemainingMilliseconds);
                        writer.Write(saved.OriginalCommandModeValue);
                        writer.Write(saved.WorkplaceLost);
                        writer.Write(saved.ResumeHoldAfterCombat);
                        writer.Write(saved.PausedHoldRemainingMilliseconds);
                        writer.Write(saved.WorkerUnitId);
                        writer.Write(saved.CommandGeneration);
                        writer.Write(saved.NextAttackRemainingMilliseconds);
                        writer.Write(saved.NextMoveRemainingMilliseconds);
                        writer.Write(saved.HasIssuedMove);
                        writer.Write(saved.IssuedMoveX);
                        writer.Write(saved.IssuedMoveY);
                        writer.Write(saved.LastProgressX);
                        writer.Write(saved.LastProgressY);
                        writer.Write(saved.MoveStallRemainingMilliseconds);
                        writer.Write(saved.StallWindowElapsedMilliseconds);
                        writer.Write(saved.StallRetryCount);
                        writer.Write(saved.Occupancy.SlotIndex);
                        writer.Write(saved.Occupancy.BuildingId);
                        writer.Write(saved.Occupancy.BuildingGlobalId);
                        writer.Write((int)saved.Occupancy.BuildingType);
                        writer.Write(saved.Occupancy.BuildingOwner);
                        writer.Write(saved.Occupancy.RequiredWorkers);
                    }
                    ExpireOwnedProjectiles(saveTick);
                    var savedProjectiles = new List<SavedOwnedProjectile>();
                    foreach (OwnedProjectile projectile in
                        _ownedProjectiles.Values)
                    {
                        SavedOwnedProjectile saved =
                            CreateSavedOwnedProjectile(projectile, saveTick);
                        if (IsValidSavedOwnedProjectile(saved))
                        {
                            savedProjectiles.Add(saved);
                        }
                    }
                    savedProjectiles.Sort(
                        (left, right) => left.ProjectileId.CompareTo(
                            right.ProjectileId));
                    if (savedProjectiles.Count > MaxOwnedProjectiles)
                    {
                        savedProjectiles.RemoveRange(
                            MaxOwnedProjectiles,
                            savedProjectiles.Count - MaxOwnedProjectiles);
                    }
                    writer.Write(savedProjectiles.Count);
                    foreach (SavedOwnedProjectile saved in savedProjectiles)
                    {
                        writer.Write(saved.ProjectileId);
                        writer.Write(saved.MilitiaGeneration);
                        writer.Write(saved.WorkerUnitId);
                        writer.Write(saved.WorkerGlobalId);
                        writer.Write(saved.WorkerOwner);
                        writer.Write((int)saved.WorkerType);
                        writer.Write(saved.TargetUnitId);
                        writer.Write(saved.TargetGlobalId);
                        writer.Write(saved.ReferenceDamage);
                        writer.Write(saved.RemainingLifetimeMilliseconds);
                    }
                    writer.Flush();
                    return stream.ToArray();
                }
            }
        }

        private void LoadMilitiaData(byte[] data, LoadContext context)
        {
            lock (_gate)
            {
                try
                {
                    if (context == null || !context.IsSaveFile
                        || data == null || data.Length == 0
                        || data.Length > 1024 * 1024)
                    {
                        return;
                    }
                    using (var stream = new MemoryStream(data, false))
                    using (var reader = new BinaryReader(stream))
                    {
                        if (reader.ReadInt32() != SaveMagic)
                        {
                            throw new InvalidDataException(
                                "Worker militia save header is unsupported");
                        }
                        int version = reader.ReadInt32();
                        if (version != LegacySaveVersion
                            && version != SaveVersion)
                        {
                            throw new InvalidDataException(
                                "Worker militia save version is unsupported");
                        }
                        SavedSelection savedSelection = null;
                        if (reader.ReadBoolean())
                        {
                            savedSelection = new SavedSelection
                            {
                                GlobalId = reader.ReadInt32(),
                                Type = (eChimps)reader.ReadInt32(),
                                Owner = reader.ReadInt32(),
                                OriginalCommandModeValue = reader.ReadUInt16(),
                                OriginalSelectionOwnerValue = reader.ReadUInt16(),
                                OriginalWorkLink = reader.ReadInt32(),
                                OriginalTribeId = reader.ReadInt32(),
                                OriginalX = reader.ReadInt32(),
                                OriginalY = reader.ReadInt32(),
                                Occupancy = new OccupancyProvenance
                                {
                                    SlotIndex = reader.ReadInt32(),
                                    BuildingId = reader.ReadInt32(),
                                    BuildingGlobalId = reader.ReadInt32(),
                                    BuildingType =
                                        (eStructs)reader.ReadInt32(),
                                    BuildingOwner = reader.ReadInt32(),
                                    RequiredWorkers = reader.ReadInt32(),
                                },
                            };
                            if (version >= SaveVersion)
                            {
                                savedSelection.UnitId = reader.ReadInt32();
                                savedSelection.LeaseGeneration =
                                    reader.ReadInt64();
                            }
                            if (!IsValidSavedSelection(
                                    savedSelection,
                                    version >= SaveVersion))
                            {
                                throw new InvalidDataException(
                                    "Worker militia saved selection is invalid");
                            }
                        }
                        int count = reader.ReadInt32();
                        if (count < 0 || count > MaxSavedCommands)
                        {
                            throw new InvalidDataException(
                                "Worker militia save command count is invalid");
                        }
                        var loaded = new List<SavedCommand>(count);
                        var loadedWorkerIds = new HashSet<int>();
                        for (int index = 0; index < count; index++)
                        {
                            var saved = new SavedCommand
                            {
                                WorkerGlobalId = reader.ReadInt32(),
                                WorkerType = (eChimps)reader.ReadInt32(),
                                Owner = reader.ReadInt32(),
                                TargetGlobalId = reader.ReadInt32(),
                                OriginX = reader.ReadInt32(),
                                OriginY = reader.ReadInt32(),
                                OriginalWorkLink = reader.ReadInt32(),
                                OriginalTribeId = reader.ReadInt32(),
                                Manual = reader.ReadBoolean(),
                                ExplicitTarget = reader.ReadBoolean(),
                                Phase = (MissionPhase)reader.ReadByte(),
                                HasManualDestination = reader.ReadBoolean(),
                                ManualDestinationReached = reader.ReadBoolean(),
                                ManualDestinationX = reader.ReadInt32(),
                                ManualDestinationY = reader.ReadInt32(),
                                CombatAnchorX = reader.ReadInt32(),
                                CombatAnchorY = reader.ReadInt32(),
                                DamageObserved = reader.ReadBoolean(),
                                HoldRemainingMilliseconds = reader.ReadInt32(),
                            };
                            if (version >= SaveVersion)
                            {
                                saved.OriginalCommandModeValue =
                                    reader.ReadUInt16();
                                saved.WorkplaceLost = reader.ReadBoolean();
                                saved.ResumeHoldAfterCombat =
                                    reader.ReadBoolean();
                                saved.PausedHoldRemainingMilliseconds =
                                    reader.ReadInt32();
                                saved.WorkerUnitId = reader.ReadInt32();
                                saved.CommandGeneration = reader.ReadInt64();
                                saved.NextAttackRemainingMilliseconds =
                                    reader.ReadInt32();
                                saved.NextMoveRemainingMilliseconds =
                                    reader.ReadInt32();
                                saved.HasIssuedMove = reader.ReadBoolean();
                                saved.IssuedMoveX = reader.ReadInt32();
                                saved.IssuedMoveY = reader.ReadInt32();
                                saved.LastProgressX = reader.ReadInt32();
                                saved.LastProgressY = reader.ReadInt32();
                                saved.MoveStallRemainingMilliseconds =
                                    reader.ReadInt32();
                                saved.StallWindowElapsedMilliseconds =
                                    reader.ReadInt32();
                                saved.StallRetryCount = reader.ReadInt32();
                            }
                            saved.Occupancy = new OccupancyProvenance
                            {
                                SlotIndex = reader.ReadInt32(),
                                BuildingId = reader.ReadInt32(),
                                BuildingGlobalId = reader.ReadInt32(),
                                BuildingType = (eStructs)reader.ReadInt32(),
                                BuildingOwner = reader.ReadInt32(),
                                RequiredWorkers = reader.ReadInt32(),
                            };
                            if (!Enum.IsDefined(
                                    typeof(MissionPhase),
                                    saved.Phase)
                                || !IsValidSavedCommand(
                                    saved,
                                    version >= SaveVersion)
                                || !loadedWorkerIds.Add(
                                    saved.WorkerGlobalId))
                            {
                                throw new InvalidDataException(
                                    "Worker militia save command is invalid");
                            }
                            loaded.Add(saved);
                        }
                        var loadedProjectiles =
                            new List<SavedOwnedProjectile>();
                        if (version >= SaveVersion)
                        {
                            int projectileCount = reader.ReadInt32();
                            if (projectileCount < 0
                                || projectileCount > MaxOwnedProjectiles)
                            {
                                throw new InvalidDataException(
                                    "Worker militia save projectile count is invalid");
                            }
                            var loadedProjectileIds = new HashSet<int>();
                            for (int index = 0;
                                index < projectileCount;
                                index++)
                            {
                                var saved = new SavedOwnedProjectile
                                {
                                    ProjectileId = reader.ReadInt32(),
                                    MilitiaGeneration = reader.ReadInt64(),
                                    WorkerUnitId = reader.ReadInt32(),
                                    WorkerGlobalId = reader.ReadInt32(),
                                    WorkerOwner = reader.ReadInt32(),
                                    WorkerType = (eChimps)reader.ReadInt32(),
                                    TargetUnitId = reader.ReadInt32(),
                                    TargetGlobalId = reader.ReadInt32(),
                                    ReferenceDamage = reader.ReadInt32(),
                                    RemainingLifetimeMilliseconds =
                                        reader.ReadInt32(),
                                };
                                if (!IsValidSavedOwnedProjectile(saved)
                                    || !loadedProjectileIds.Add(
                                        saved.ProjectileId))
                                {
                                    throw new InvalidDataException(
                                        "Worker militia save projectile is invalid");
                                }
                                loadedProjectiles.Add(saved);
                            }
                        }
                        if (stream.Position != stream.Length)
                        {
                            throw new InvalidDataException(
                                "Worker militia save has trailing bytes");
                        }
                        _pendingSavedSelection = savedSelection;
                        _pendingSavedCommands = loaded;
                        _pendingSavedProjectiles = loadedProjectiles;
                        _pendingSaveVersion = version;
                    }
                }
                catch (Exception exception)
                {
                    _pendingSavedSelection = null;
                    _pendingSavedCommands = null;
                    _pendingSavedProjectiles = null;
                    _pendingSaveVersion = 0;
                    _warning(
                        "Worker militia ignored invalid save data: "
                        + exception.Message);
                }
            }
        }

        /// <summary>
        /// Restores the missions and the selection a save file carried.
        /// </summary>
        /// <remarks>
        /// Every discard below is legitimate - the worker died between saving
        /// and loading, its workplace changed, the slot went to somebody else.
        /// Until 2026-08-27 all of them were silent, and so was the success
        /// case: a load left no trace whatsoever in the log. That is why this
        /// path is the one mechanism of the feature that has never been
        /// confirmed in any run of this project, despite being complete. It
        /// says what it did now, so one ordinary save and reload settles it.
        /// </remarks>
        private void RestorePendingSaveData()
        {
            List<SavedCommand> savedCommands = _pendingSavedCommands;
            SavedSelection savedSelection = _pendingSavedSelection;
            List<SavedOwnedProjectile> savedProjectiles =
                _pendingSavedProjectiles;
            int saveVersion = _pendingSaveVersion;
            _pendingSavedCommands = null;
            _pendingSavedSelection = null;
            _pendingSavedProjectiles = null;
            _pendingSaveVersion = 0;
            if (saveVersion == LegacySaveVersion)
            {
                RetireLegacySavedState(savedCommands, savedSelection);
                return;
            }
            int restored = 0;
            int discarded = 0;
            if (savedCommands != null)
            {
                int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
                foreach (SavedCommand saved in savedCommands)
                {
                    int workerId = GameUnitManagerAPI.Instance.GetByGlobalId(
                        saved.WorkerGlobalId);
                    UnitSnapshot worker = CaptureUnit(workerId);
                    if (saved.WorkplaceLost)
                    {
                        TryReleasePersistedCommandMode(
                            saved,
                            false,
                            "v4 workplace-lost cleanup");
                        discarded++;
                        continue;
                    }
                    bool exactWorkerIdentity = worker != null
                        && workerId == saved.WorkerUnitId
                        && worker.GlobalId == saved.WorkerGlobalId
                        && worker.Type == saved.WorkerType
                        && worker.Owner == saved.Owner
                        && worker.Owner == localPlayer;
                    bool liveCommandOwnsWorker = exactWorkerIdentity
                        && _commands.ContainsKey(workerId);
                    if (!exactWorkerIdentity || liveCommandOwnsWorker)
                    {
                        discarded++;
                        LogSaveRestoreDiscard(
                            saved,
                            workerId,
                            worker,
                            localPlayer);
                        continue;
                    }
                    bool workProvenanceMatches =
                        worker.WorkLink == saved.OriginalWorkLink
                        && worker.TribeId == saved.OriginalTribeId
                        && WorkerOccupancyMatches(
                            workerId,
                            saved.WorkerGlobalId,
                            saved.Owner,
                            saved.WorkerType,
                            saved.Occupancy);
                    if (WorkerMilitiaSafetyRules.ShouldReleasePersistedCommandMode(
                            exactWorkerIdentity,
                            liveCommandOwnsWorker,
                            workProvenanceMatches))
                    {
                        bool released = TryReleasePersistedCommandMode(
                            saved,
                            false,
                            "v4 stale work-provenance cleanup");
                        discarded++;
                        LogSaveRestoreDiscard(
                            saved,
                            workerId,
                            worker,
                            localPlayer);
                        if (!released)
                        {
                            _warning(
                                "Worker militia discarded a stale v4 mission "
                                + "but could not prove release of its exact "
                                + "persisted command mode: global_id="
                                + saved.WorkerGlobalId.ToString(
                                    CultureInfo.InvariantCulture) + ".");
                        }
                        continue;
                    }
                    if (saved.Phase == MissionPhase.Fighting
                        && !CanEnterMilitiaCombat(saved.WorkerType))
                    {
                        bool released = TryReleasePersistedCommandMode(
                            saved,
                            true,
                            "uncalibrated hunter combat cleanup");
                        discarded++;
                        if (!released)
                        {
                            _warning(
                                "Worker militia discarded an uncalibrated "
                                + "hunter combat mission but could not prove "
                                + "release of its exact persisted command mode: "
                                + "global_id="
                                + saved.WorkerGlobalId.ToString(
                                    CultureInfo.InvariantCulture) + ".");
                        }
                        continue;
                    }
                    int targetId = saved.TargetGlobalId <= 0
                        ? 0
                        : GameUnitManagerAPI.Instance.GetByGlobalId(
                            saved.TargetGlobalId);
                    UnitSnapshot target = targetId > 0
                        ? CaptureUnit(targetId)
                        : null;
                    bool targetValid = target != null
                        && target.GlobalId == saved.TargetGlobalId
                        && IsEnemyPlayerUnit(worker.Owner, target.Owner)
                        && CanDamage(saved.WorkerType, target.Type);
                    if (saved.Phase == MissionPhase.Fighting
                        && saved.Manual
                        && saved.ExplicitTarget
                        && !targetValid)
                    {
                        TryReleasePersistedCommandMode(
                            saved,
                            true,
                            "invalid restored manual target");
                        discarded++;
                        continue;
                    }
                    int restoreTick = SimulationNowMilliseconds();
                    bool nativeMoveContinues = saved.HasIssuedMove
                        && NativeMoveDestinationMatches(
                            workerId,
                            saved.IssuedMoveX,
                            saved.IssuedMoveY);
                    _commandGeneration = Math.Max(
                        _commandGeneration,
                        saved.CommandGeneration);
                    var command = new CommandState
                    {
                        Generation = saved.CommandGeneration,
                        WorkerUnitId = workerId,
                        WorkerGlobalId = worker.GlobalId,
                        WorkerOwner = worker.Owner,
                        WorkerType = saved.WorkerType,
                        TargetUnitId = targetId,
                        TargetGlobalId = saved.TargetGlobalId,
                        OriginX = saved.OriginX,
                        OriginY = saved.OriginY,
                        OriginalWorkLink = saved.OriginalWorkLink,
                        OriginalTribeId = saved.OriginalTribeId,
                        Manual = saved.Manual,
                        ExplicitTarget = saved.ExplicitTarget,
                        Phase = saved.Phase,
                        HasManualDestination = saved.HasManualDestination,
                        ManualDestinationReached =
                            saved.ManualDestinationReached,
                        ManualDestinationX = saved.ManualDestinationX,
                        ManualDestinationY = saved.ManualDestinationY,
                        CombatAnchorX = saved.CombatAnchorX,
                        CombatAnchorY = saved.CombatAnchorY,
                        DamageObserved = saved.DamageObserved,
                        OriginalCommandModeValue =
                            saved.OriginalCommandModeValue,
                        WorkplaceLost = saved.WorkplaceLost,
                        ResumeHoldAfterCombat = saved.ResumeHoldAfterCombat,
                        PausedHoldRemainingMilliseconds =
                            saved.PausedHoldRemainingMilliseconds,
                        NextAttackTick = unchecked(
                            restoreTick
                            + saved.NextAttackRemainingMilliseconds),
                        NextMoveTick = nativeMoveContinues
                            ? unchecked(
                                restoreTick
                                + saved.NextMoveRemainingMilliseconds)
                            : restoreTick,
                        HasIssuedMove = nativeMoveContinues,
                        IssuedMoveX = saved.IssuedMoveX,
                        IssuedMoveY = saved.IssuedMoveY,
                        LastProgressX = nativeMoveContinues
                            ? saved.LastProgressX
                            : worker.X,
                        LastProgressY = nativeMoveContinues
                            ? saved.LastProgressY
                            : worker.Y,
                        LastProgressTick = nativeMoveContinues
                            ? unchecked(
                                restoreTick
                                - (MoveStallMilliseconds
                                    - saved.MoveStallRemainingMilliseconds))
                            : restoreTick,
                        StallWindowStartTick = nativeMoveContinues
                            ? unchecked(
                                restoreTick
                                - saved.StallWindowElapsedMilliseconds)
                            : restoreTick,
                        StallRetryCount = nativeMoveContinues
                            ? saved.StallRetryCount
                            : 0,
                        HoldDeadlineTick = saved.Phase
                                == MissionPhase.Holding
                            ? unchecked(
                                restoreTick
                                + saved.HoldRemainingMilliseconds)
                            : 0,
                        Occupancy = CopyOccupancy(saved.Occupancy),
                    };
                    if (command.Phase == MissionPhase.Fighting
                        && !targetValid)
                    {
                        command.ExplicitTarget = false;
                        command.TargetUnitId = 0;
                        command.TargetGlobalId = 0;
                        // Keep Fighting for one authoritative scan. That scan
                        // either acquires a live replacement, resumes an
                        // interrupted outbound destination, or hands the
                        // worker directly back to its preserved work.
                    }
                    if (!EnsureCommandMode(command, true))
                    {
                        discarded++;
                        if (_saveRestoreLogged < MaxSaveRestoreLogs)
                        {
                            _saveRestoreLogged++;
                            _warning(
                                "Worker militia could not take the command mode "
                                + "back for a restored mission: unit_id="
                                + workerId.ToString(CultureInfo.InvariantCulture)
                                + " type=" + UnitName(saved.WorkerType)
                                + ". That mission is dropped.");
                        }
                        continue;
                    }
                    _commands.Add(workerId, command);
                    restored++;
                }
            }
            bool reclaimedSelection = false;
            if (savedSelection != null)
            {
                ReclaimLoadedNativeSelection(savedSelection);
                reclaimedSelection = _selectionLease != null;
            }
            int restoredProjectiles = RestoreSavedProjectiles(
                savedProjectiles);
            if (savedCommands != null
                || savedSelection != null
                || savedProjectiles != null)
            {
                _info(
                    "Worker militia restored its saved state: missions_in_save="
                    + (savedCommands == null
                        ? 0
                        : savedCommands.Count).ToString(
                            CultureInfo.InvariantCulture)
                    + " restored=" + restored.ToString(CultureInfo.InvariantCulture)
                    + " discarded=" + discarded.ToString(CultureInfo.InvariantCulture)
                    + " selection_in_save="
                    + TelemetryBoolean(savedSelection != null)
                    + " selection_reclaimed="
                    + TelemetryBoolean(reclaimedSelection)
                    + " projectiles_in_save="
                    + (savedProjectiles == null ? 0 : savedProjectiles.Count)
                        .ToString(CultureInfo.InvariantCulture)
                    + " projectiles_restored="
                    + restoredProjectiles.ToString(
                        CultureInfo.InvariantCulture)
                    + ".");
            }
        }

        private void RetireLegacySavedState(
            List<SavedCommand> savedCommands,
            SavedSelection savedSelection)
        {
            int released = 0;
            if (savedCommands != null)
            {
                foreach (SavedCommand saved in savedCommands)
                {
                    if (TryReleasePersistedCommandMode(
                            saved,
                            true,
                            "v3 migration"))
                    {
                        released++;
                    }
                }
            }
            if (savedSelection != null)
            {
                ReclaimLoadedNativeSelection(savedSelection);
            }
            _info(
                "Worker militia retired legacy v3 save state without "
                + "resuming missions: missions_in_save="
                + (savedCommands == null ? 0 : savedCommands.Count).ToString(
                    CultureInfo.InvariantCulture)
                + " exact_command_modes_released="
                + released.ToString(CultureInfo.InvariantCulture)
                + " selection_cleanup_queued="
                + TelemetryBoolean(_selectionLease != null) + ".");
        }

        private bool TryReleasePersistedCommandMode(
            SavedCommand saved,
            bool requireWorkProvenance,
            string reason)
        {
            if (saved == null)
            {
                return false;
            }
            int workerId = GameUnitManagerAPI.Instance.GetByGlobalId(
                saved.WorkerGlobalId);
            UnitSnapshot worker = CaptureUnit(workerId);
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            if (worker == null
                || (saved.WorkerUnitId > 0
                    && workerId != saved.WorkerUnitId)
                || worker.GlobalId != saved.WorkerGlobalId
                || worker.Owner != saved.Owner
                || worker.Owner != localPlayer
                || worker.Type != saved.WorkerType
                || (requireWorkProvenance
                    && (worker.WorkLink != saved.OriginalWorkLink
                        || worker.TribeId != saved.OriginalTribeId
                        || !WorkerOccupancyMatches(
                            workerId,
                            saved.WorkerGlobalId,
                            saved.Owner,
                            saved.WorkerType,
                            saved.Occupancy)))
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    workerId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (SeInteropFieldAliases.CommandMode(ref unit) == saved.OriginalCommandModeValue)
            {
                return true;
            }
            if (SeInteropFieldAliases.CommandMode(ref unit) != 1)
            {
                return false;
            }
            SeInteropFieldAliases.CommandMode(ref unit) = saved.OriginalCommandModeValue;
            bool released = SeInteropFieldAliases.CommandMode(ref unit)
                == saved.OriginalCommandModeValue;
            if (released)
            {
                _info(
                    "Worker militia released an identity-bound persisted "
                    + "command mode during " + reason + ": global_id="
                    + saved.WorkerGlobalId.ToString(
                        CultureInfo.InvariantCulture) + ".");
            }
            return released;
        }

        private int RestoreSavedProjectiles(
            List<SavedOwnedProjectile> savedProjectiles)
        {
            if (savedProjectiles == null || savedProjectiles.Count == 0)
            {
                return 0;
            }
            int now = SimulationNowMilliseconds();
            int restored = 0;
            foreach (SavedOwnedProjectile saved in savedProjectiles)
            {
                int targetId = GameUnitManagerAPI.Instance.GetByGlobalId(
                    saved.TargetGlobalId);
                UnitSnapshot target = CaptureUnit(targetId);
                if (target == null
                    || target.GlobalId != saved.TargetGlobalId
                    || !IsEnemyPlayerUnit(saved.WorkerOwner, target.Owner)
                    || !CanDamage(saved.WorkerType, target.Type)
                    || _ownedProjectiles.ContainsKey(saved.ProjectileId))
                {
                    continue;
                }
                int workerId = GameUnitManagerAPI.Instance.GetByGlobalId(
                    saved.WorkerGlobalId);
                UnitSnapshot worker = CaptureUnit(workerId);
                if (worker == null
                    || worker.GlobalId != saved.WorkerGlobalId
                    || worker.Owner != saved.WorkerOwner
                    || worker.Type != saved.WorkerType)
                {
                    // The projectile remains owned even after its shooter
                    // dies. In that case the event continues to carry the
                    // serialized native attacker slot.
                    workerId = saved.WorkerUnitId;
                }
                _ownedProjectiles.Add(
                    saved.ProjectileId,
                    new OwnedProjectile
                    {
                        ProjectileId = saved.ProjectileId,
                        MilitiaGeneration = saved.MilitiaGeneration,
                        WorkerUnitId = workerId,
                        WorkerGlobalId = saved.WorkerGlobalId,
                        WorkerOwner = saved.WorkerOwner,
                        WorkerType = saved.WorkerType,
                        TargetUnitId = targetId,
                        TargetGlobalId = saved.TargetGlobalId,
                        ReferenceDamage = saved.ReferenceDamage,
                        DeadlineTick = unchecked(
                            now + saved.RemainingLifetimeMilliseconds),
                    });
                restored++;
            }
            return restored;
        }

        /// <summary>
        /// Names why one saved mission could not be restored. Capped, and
        /// deliberately specific: "the worker is gone" and "its workplace
        /// changed" call for very different answers.
        /// </summary>
        private void LogSaveRestoreDiscard(
            SavedCommand saved,
            int workerId,
            UnitSnapshot worker,
            int localPlayer)
        {
            if (_saveRestoreLogged >= MaxSaveRestoreLogs)
            {
                return;
            }
            _saveRestoreLogged++;
            string reason;
            if (worker == null)
            {
                reason = "the worker no longer exists";
            }
            else if (worker.GlobalId != saved.WorkerGlobalId
                || worker.Type != saved.WorkerType)
            {
                reason = "the unit slot belongs to somebody else now";
            }
            else if (worker.Owner != saved.Owner || worker.Owner != localPlayer)
            {
                reason = "the worker changed owner";
            }
            else if (worker.WorkLink != saved.OriginalWorkLink)
            {
                reason = "its workplace changed (work_link="
                    + worker.WorkLink.ToString(CultureInfo.InvariantCulture)
                    + " saved="
                    + saved.OriginalWorkLink.ToString(CultureInfo.InvariantCulture)
                    + ")";
            }
            else if (worker.TribeId != saved.OriginalTribeId)
            {
                reason = "its tribe changed";
            }
            else if (_commands.ContainsKey(workerId))
            {
                reason = "a live mission already owns it";
            }
            else
            {
                reason = "its building occupancy changed";
            }
            _warning(
                "Worker militia dropped a saved mission on load: global_id="
                + saved.WorkerGlobalId.ToString(CultureInfo.InvariantCulture)
                + " type=" + UnitName(saved.WorkerType)
                + " reason=" + reason + ".");
        }

        private void ReclaimLoadedNativeSelection(SavedSelection saved)
        {
            int unitId = GameUnitManagerAPI.Instance.GetByGlobalId(
                saved.GlobalId);
            UnitSnapshot worker = CaptureUnit(unitId);
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            if (worker == null
                || (saved.UnitId > 0 && unitId != saved.UnitId)
                || worker.GlobalId != saved.GlobalId
                || worker.Type != saved.Type
                || worker.Owner != saved.Owner
                || worker.Owner != localPlayer
                || worker.WorkLink != saved.OriginalWorkLink
                || worker.TribeId != saved.OriginalTribeId
                || !WorkerOccupancyMatches(
                    unitId,
                    saved.GlobalId,
                    saved.Owner,
                    saved.Type,
                    saved.Occupancy)
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                _warning(
                    "Worker militia discarded saved selection cleanup after "
                    + "its identity or work/tribe provenance changed.");
                return;
            }
            CommandState activeCommand = null;
            bool retainCommandMode = _commands.TryGetValue(
                    unitId,
                    out activeCommand)
                && activeCommand.WorkerGlobalId == saved.GlobalId
                && activeCommand.WorkerOwner == saved.Owner
                && activeCommand.WorkerType == saved.Type
                && activeCommand.OriginalCommandModeValue
                    == saved.OriginalCommandModeValue
                && activeCommand.OriginalWorkLink == saved.OriginalWorkLink
                && activeCommand.OriginalTribeId == saved.OriginalTribeId
                && OccupancyProvenanceMatches(
                    activeCommand.Occupancy,
                    saved.Occupancy);
            ref GameUnit unit = ref pointer.AsRef();
            ushort expectedCommandMode = retainCommandMode
                ? (ushort)1
                : saved.OriginalCommandModeValue;
            bool nativeSelectionAlreadyReset = unit.r_UnitHover == 0
                && unit.r_UnitSelected == saved.OriginalSelectionOwnerValue
                && SeInteropFieldAliases.CommandMode(ref unit) == expectedCommandMode;
            if (nativeSelectionAlreadyReset)
            {
                _warning(
                    "Worker militia dropped saved UI selection after native "
                    + "load reset its transient fields; mission state was preserved.");
                return;
            }
            bool ownsPersistedFields =
                (SeInteropFieldAliases.CommandMode(ref unit) == 1
                    || SeInteropFieldAliases.CommandMode(ref unit) == saved.OriginalCommandModeValue)
                && (unit.r_UnitSelected == saved.Owner
                    || unit.r_UnitSelected
                        == saved.OriginalSelectionOwnerValue)
                && (unit.r_UnitHover == 0
                    || unit.r_UnitSelected == saved.Owner);
            if (!ownsPersistedFields)
            {
                _warning(
                    "Worker militia preserved foreign native fields while "
                    + "dropping a saved UI selection.");
                return;
            }
            _selectionLeaseGeneration = Math.Max(
                _selectionLeaseGeneration,
                saved.LeaseGeneration);
            _selectionLease = new NativeSelectionLease
            {
                Generation = ++_selectionLeaseGeneration,
                UnitId = unitId,
                GlobalId = saved.GlobalId,
                Owner = saved.Owner,
                Type = saved.Type,
                OriginalCommandModeValue = saved.OriginalCommandModeValue,
                OriginalSelectionOwnerValue =
                    saved.OriginalSelectionOwnerValue,
                OriginalWorkLink = saved.OriginalWorkLink,
                OriginalTribeId = saved.OriginalTribeId,
                OriginalX = saved.OriginalX,
                OriginalY = saved.OriginalY,
                Occupancy = CopyOccupancy(saved.Occupancy),
            };
            _selectedWorkerId = unit.r_UnitHover != 0 ? unitId : 0;
            _nativeSelectionLifecycle = NativeSelectionLifecycle.Confirmed;
            RequestSelectionReleaseAtNativeBoundary("saved selection cleanup");
            _warning(
                "Worker militia queued safe saved-UI-selection cleanup for unit_id="
                + unitId.ToString(CultureInfo.InvariantCulture)
                + " at the next native run boundary; a fresh native click is "
                + "required to select it again.");
        }

        private MethodInfo FindNativeInputTarget()
        {
            MethodInfo target = typeof(EditorDirector).GetMethod(
                "getMouseStateForEngine",
                BindingFlags.NonPublic
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly,
                null,
                new[]
                {
                    typeof(bool).MakeByRefType(),
                    typeof(bool).MakeByRefType(),
                },
                null);
            if (target == null || target.ReturnType != typeof(int))
            {
                throw new MissingMethodException(
                    "Exact EditorDirector.getMouseStateForEngine(ref bool, ref bool) target was not found");
            }
            ParameterInfo[] parameters = target.GetParameters();
            if (parameters.Length != 2
                || !string.Equals(parameters[0].Name, "rightDown", StringComparison.Ordinal)
                || !string.Equals(parameters[1].Name, "rightUp", StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Native mouse-state target parameter names changed");
            }
            return target;
        }

        private static MethodInfo FindNativeRunTarget()
        {
            MethodInfo target = typeof(EngineInterface).GetMethod(
                "run",
                BindingFlags.NonPublic
                    | BindingFlags.Public
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(bool) },
                null);
            if (target == null || target.ReturnType != typeof(int))
            {
                throw new MissingMethodException(
                    "Exact EngineInterface.run(bool) target was not found");
            }
            ParameterInfo[] parameters = target.GetParameters();
            if (parameters.Length != 1
                || !string.Equals(
                    parameters[0].Name,
                    "mpFrameSkip",
                    StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Native EngineInterface.run parameter changed");
            }
            return target;
        }

        private static MethodInfo FindNativeSelectedTroopsTarget()
        {
            MethodInfo target = typeof(EditorDirector).GetMethod(
                "updateDLLSelectedTroops",
                BindingFlags.Public
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(EngineInterface.PlayState), typeof(bool) },
                null);
            if (target == null || target.ReturnType != typeof(void))
            {
                throw new MissingMethodException(
                    "Exact EditorDirector.updateDLLSelectedTroops(PlayState, bool) target was not found");
            }
            ParameterInfo[] parameters = target.GetParameters();
            if (parameters.Length != 2
                || parameters[0].ParameterType != typeof(EngineInterface.PlayState)
                || parameters[1].ParameterType != typeof(bool)
                || !string.Equals(
                    parameters[0].Name,
                    "gameState",
                    StringComparison.Ordinal)
                || !string.Equals(
                    parameters[1].Name,
                    "inTroopUI",
                    StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Managed troop-selection gate signature changed");
            }
            return target;
        }

        private static MethodInfo FindTroopsSelectedUiTarget()
        {
            MethodInfo target = typeof(MainViewModel).GetMethod(
                "TroopsSelectedGameAction",
                BindingFlags.Public
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(bool) },
                null);
            if (target == null || target.ReturnType != typeof(void))
            {
                throw new MissingMethodException(
                    "Exact MainViewModel.TroopsSelectedGameAction(bool) target was not found");
            }
            ParameterInfo[] parameters = target.GetParameters();
            if (parameters.Length != 1
                || !string.Equals(
                    parameters[0].Name,
                    "fromInitialOpening",
                    StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Troop-selection UI target parameter changed");
            }
            MethodInfo workerInfoUi = typeof(MainViewModel).GetMethod(
                "InBuildingGameAction",
                BindingFlags.Public
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly,
                null,
                Type.EmptyTypes,
                null);
            if (workerInfoUi == null
                || workerInfoUi.ReturnType != typeof(void))
            {
                throw new MissingMethodException(
                    "Exact MainViewModel.InBuildingGameAction() target was not found");
            }
            return target;
        }

        private static MethodInfo FindHunterHutCanPlaceTarget()
        {
            MethodInfo target = typeof(MainViewModel).GetMethod(
                "CanPlaceMapper",
                BindingFlags.Public
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { typeof(object) },
                null);
            if (target == null || target.ReturnType != typeof(bool))
            {
                throw new MissingMethodException(
                    "Exact MainViewModel.CanPlaceMapper(object) target was not found");
            }
            ParameterInfo[] parameters = target.GetParameters();
            if (parameters.Length != 1
                || !string.Equals(
                    parameters[0].Name,
                    "parameter",
                    StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Hunter-hut can-place target parameter changed");
            }
            return target;
        }

        private static FieldInfo FindNativeSelectionBoxField()
        {
            return FindNativeField("troopSelectionBoxOn", typeof(bool));
        }

        private static FieldInfo FindNativeField(string name, Type fieldType)
        {
            FieldInfo field = typeof(EditorDirector).GetField(
                name,
                BindingFlags.NonPublic
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly);
            if (field == null || field.FieldType != fieldType)
            {
                throw new MissingFieldException(
                    "Exact EditorDirector." + name + " field was not found as "
                    + fieldType.FullName);
            }
            return field;
        }

        private void InstallNativeInputPatch()
        {
            lock (InputOwnerGate)
            {
                if (_inputOwner != null && !ReferenceEquals(_inputOwner, this))
                {
                    throw new InvalidOperationException(
                        "Another worker militia input owner is already active");
                }
                _inputOwner = this;
            }
            try
            {
                MethodInfo postfix = typeof(WorkerMilitiaFeature).GetMethod(
                    "NativeMouseStatePostfix",
                    BindingFlags.NonPublic | BindingFlags.Static);
                if (postfix == null)
                {
                    throw new MissingMethodException(
                        "Worker militia native mouse-state postfix is missing");
                }
                _harmony.Patch(
                    _nativeInputTarget,
                    postfix: new HarmonyMethod(postfix));
                _inputPatchApplied = true;
                MethodInfo runPostfix = typeof(WorkerMilitiaFeature).GetMethod(
                    "NativeRunPostfix",
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo runPrefix = typeof(WorkerMilitiaFeature).GetMethod(
                    "NativeRunPrefix",
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo runFinalizer = typeof(WorkerMilitiaFeature).GetMethod(
                    "NativeRunFinalizer",
                    BindingFlags.NonPublic | BindingFlags.Static);
                if (runPrefix == null
                    || runPostfix == null
                    || runFinalizer == null)
                {
                    throw new MissingMethodException(
                        "Worker militia native run prefix/postfix/finalizer is missing");
                }
                _harmony.Patch(
                    _nativeRunTarget,
                    prefix: new HarmonyMethod(runPrefix),
                    postfix: new HarmonyMethod(runPostfix),
                    finalizer: new HarmonyMethod(runFinalizer));
                _nativeRunPatchApplied = true;
                MethodInfo selectedTroopsPrefix =
                    typeof(WorkerMilitiaFeature).GetMethod(
                        "NativeSelectedTroopsPrefix",
                        BindingFlags.NonPublic | BindingFlags.Static);
                if (selectedTroopsPrefix == null)
                {
                    throw new MissingMethodException(
                        "Worker militia managed troop-selection gate prefix is missing");
                }
                _harmony.Patch(
                    _nativeSelectedTroopsTarget,
                    prefix: new HarmonyMethod(selectedTroopsPrefix));
                _nativeSelectedTroopsPatchApplied = true;
                MethodInfo uiPrefix = typeof(WorkerMilitiaFeature).GetMethod(
                    "TroopsSelectedUiPrefix",
                    BindingFlags.NonPublic | BindingFlags.Static);
                if (uiPrefix == null)
                {
                    throw new MissingMethodException(
                        "Worker militia troop-selection UI prefix is missing");
                }
                _harmony.Patch(
                    _troopsSelectedUiTarget,
                    prefix: new HarmonyMethod(uiPrefix));
                _troopsSelectedUiPatchApplied = true;
                MethodInfo canPlacePostfix = typeof(WorkerMilitiaFeature).GetMethod(
                    "HunterHutCanPlacePostfix",
                    BindingFlags.NonPublic | BindingFlags.Static);
                if (canPlacePostfix == null)
                {
                    throw new MissingMethodException(
                        "Worker militia hunter-hut can-place postfix is missing");
                }
                _harmony.Patch(
                    _hunterHutCanPlaceTarget,
                    postfix: new HarmonyMethod(canPlacePostfix));
                _hunterHutCanPlacePatchApplied = true;
            }
            catch
            {
                if (_inputPatchApplied)
                {
                    _harmony.Unpatch(
                        _nativeInputTarget,
                        HarmonyPatchType.Postfix,
                        _harmony.Id);
                    _inputPatchApplied = false;
                }
                if (_hunterHutCanPlacePatchApplied)
                {
                    _harmony.Unpatch(
                        _hunterHutCanPlaceTarget,
                        HarmonyPatchType.Postfix,
                        _harmony.Id);
                    _hunterHutCanPlacePatchApplied = false;
                }
                if (_troopsSelectedUiPatchApplied)
                {
                    _harmony.Unpatch(
                        _troopsSelectedUiTarget,
                        HarmonyPatchType.Prefix,
                        _harmony.Id);
                    _troopsSelectedUiPatchApplied = false;
                }
                if (_nativeSelectedTroopsPatchApplied)
                {
                    _harmony.Unpatch(
                        _nativeSelectedTroopsTarget,
                        HarmonyPatchType.Prefix,
                        _harmony.Id);
                    _nativeSelectedTroopsPatchApplied = false;
                }
                if (_nativeRunPatchApplied)
                {
                    _harmony.Unpatch(
                        _nativeRunTarget,
                        HarmonyPatchType.Prefix,
                        _harmony.Id);
                    _harmony.Unpatch(
                        _nativeRunTarget,
                        HarmonyPatchType.Postfix,
                        _harmony.Id);
                    _harmony.Unpatch(
                        _nativeRunTarget,
                        HarmonyPatchType.Finalizer,
                        _harmony.Id);
                    _nativeRunPatchApplied = false;
                }
                lock (InputOwnerGate)
                {
                    if (ReferenceEquals(_inputOwner, this))
                    {
                        _inputOwner = null;
                    }
                }
                throw;
            }
        }

        private void RemoveNativeInputPatch()
        {
            lock (InputOwnerGate)
            {
                if (ReferenceEquals(_inputOwner, this))
                {
                    _inputOwner = null;
                }
            }
            if (!_inputPatchApplied || _nativeInputTarget == null)
            {
                // The UI postfix is independent from the input postfix and may
                // still need removal after a partial application.
            }
            else
            {
                _inputPatchApplied = false;
                _harmony.Unpatch(
                    _nativeInputTarget,
                    HarmonyPatchType.Postfix,
                    _harmony.Id);
            }
            if (_hunterHutCanPlacePatchApplied
                && _hunterHutCanPlaceTarget != null)
            {
                _hunterHutCanPlacePatchApplied = false;
                _harmony.Unpatch(
                    _hunterHutCanPlaceTarget,
                    HarmonyPatchType.Postfix,
                    _harmony.Id);
            }
            if (_troopsSelectedUiPatchApplied
                && _troopsSelectedUiTarget != null)
            {
                _troopsSelectedUiPatchApplied = false;
                _harmony.Unpatch(
                    _troopsSelectedUiTarget,
                    HarmonyPatchType.Prefix,
                    _harmony.Id);
            }
            if (_nativeSelectedTroopsPatchApplied
                && _nativeSelectedTroopsTarget != null)
            {
                _nativeSelectedTroopsPatchApplied = false;
                _harmony.Unpatch(
                    _nativeSelectedTroopsTarget,
                    HarmonyPatchType.Prefix,
                    _harmony.Id);
            }
            if (_nativeRunPatchApplied
                && _nativeRunTarget != null)
            {
                _nativeRunPatchApplied = false;
                _harmony.Unpatch(
                    _nativeRunTarget,
                    HarmonyPatchType.Prefix,
                    _harmony.Id);
                _harmony.Unpatch(
                    _nativeRunTarget,
                    HarmonyPatchType.Postfix,
                    _harmony.Id);
                _harmony.Unpatch(
                    _nativeRunTarget,
                    HarmonyPatchType.Finalizer,
                    _harmony.Id);
            }
        }

        private static void HunterHutCanPlacePostfix(
            object parameter,
            ref bool __result)
        {
            if (!string.Equals(
                    parameter as string,
                    "STRUCT_HUNTERS_HUT",
                    StringComparison.Ordinal))
            {
                return;
            }
            WorkerMilitiaFeature owner;
            lock (InputOwnerGate)
            {
                owner = _inputOwner;
            }
            // The hunter-hut build-menu unlock is an existing independent
            // feature and intentionally remains available in network maps.
            // Only worker selection, commands and combat use the MP gate.
            if (owner != null
                && owner._mapApplied
                && GamePlayerManagerAPI.Instance.GetBuildingAvailability(
                    eMappers.MAPPER_HUNTER))
            {
                __result = true;
            }
        }

        private static void NativeMouseStatePostfix(
            EditorDirector __instance,
            ref bool rightDown,
            ref bool rightUp,
            ref int __result)
        {
            WorkerMilitiaFeature owner;
            lock (InputOwnerGate)
            {
                owner = _inputOwner;
            }
            if (owner == null
                || !owner._mapApplied
                || owner._networkSuppressed
                || owner._selectionQuarantineSuppressed
                || ((__result < 1 || __result > 3) && !rightDown && !rightUp))
            {
                return;
            }
            int vanillaResult = __result;
            bool vanillaRightDown = rightDown;
            bool vanillaRightUp = rightUp;
            try
            {
                lock (owner._gate)
                {
                if (!owner.IsOperationalLocked())
                {
                    owner._pendingRightClickGesture = null;
                    return;
                }
                int nativeMouseState = __result;
                bool neutralizeConfirmedGesture = false;
                bool capturedRightDown = rightDown;
                bool capturedRightUp = rightUp;
                bool capturedRightEdge = capturedRightDown || capturedRightUp;
                int hovered = GamePlayerManagerAPI.Instance == null
                    ? 0
                    : GamePlayerManagerAPI.Instance.GetHoveredUnitId();
                var mapMouse = __instance.GetMapMousePos();
                bool hasGroundDestination = capturedRightDown
                    && !__instance.overUI()
                    && IsValidMapTile(mapMouse.x, mapMouse.y);
                bool rawSelectionBox =
                    (bool)owner._nativeSelectionBoxField.GetValue(__instance);
                bool boxSelection = owner.IsGenuineNativeSelectionBox(
                    __instance,
                    rawSelectionBox,
                    out float selectionDeltaX,
                    out float selectionDeltaY);
                bool selectionModifier = KeyManager.instance != null
                    && (KeyManager.instance.isShiftDown()
                        || KeyManager.instance.isCtrlDown()
                        || KeyManager.instance.isAltDown());
                // Classic (DE) troop controls issue move/attack by LEFT-click:
                // with a confirmed militia worker selected, a left-click on
                // empty ground moves it and a left-click on an enemy attacks,
                // exactly like a normal troop. The native left click is
                // suppressed for this case so the engine neither deselects the
                // worker nor tries a tribe order it cannot run; the worker
                // therefore stays selected across commands. Right-click still
                // works for players on the SH1 RTS control scheme.
                bool leftCommandDown = false;
                bool leftCommandUp = false;
                bool leftGroundDestination = false;
                int leftCommandWorkerId;
                // A click on a building must keep reaching the game, otherwise
                // its panel would never open while a militia worker is
                // selected. Only an enemy unit, or bare terrain with no
                // building under the cursor, becomes a militia order.
                int hoveredBuilding = GamePlayerManagerAPI.Instance == null
                    ? 0
                    : GamePlayerManagerAPI.Instance.GetHoveredBuildingId();
                bool leftCommandCandidate = !capturedRightEdge
                    && !boxSelection
                    && !selectionModifier
                    && (nativeMouseState >= 1 && nativeMouseState <= 3)
                    && owner.HasConfirmedCommandableMilitia(
                        out leftCommandWorkerId)
                    && hovered != leftCommandWorkerId
                    && (owner.IsEnemyOfLocalPlayer(hovered)
                        || (hovered == 0 && hoveredBuilding == 0));
                if (leftCommandCandidate)
                {
                    if (nativeMouseState == 1)
                    {
                        leftCommandDown = true;
                        leftGroundDestination = hovered == 0
                            && !__instance.overUI()
                            && IsValidMapTile(mapMouse.x, mapMouse.y);
                    }
                    else if (nativeMouseState == 3)
                    {
                        leftCommandUp = true;
                    }
                    // Never let the engine consume this left click.
                    __result = 0;
                }
                else if (!capturedRightEdge
                    && nativeMouseState == 1
                    && !boxSelection
                    && !selectionModifier
                    && IsLocalMilitia(hovered))
                {
                    owner.TryBeginNativeDirectClick(__instance, hovered);
                    neutralizeConfirmedGesture =
                        owner.IsConfirmedNativeDirectClickNoOp();
                }
                else if (!capturedRightEdge
                    && (nativeMouseState == 2 || nativeMouseState == 3)
                    && (owner.HasOutstandingNativeSelection()
                        || owner.HasActiveNativeDirectClickGesture()))
                {
                    neutralizeConfirmedGesture =
                        owner.IsConfirmedNativeDirectClickNoOp();
                    if (boxSelection || selectionModifier)
                    {
                        owner.CancelNativeDirectClickGesture(
                            __instance,
                            "modified or boxed direct click",
                            false);
                        neutralizeConfirmedGesture = false;
                    }
                    else if (nativeMouseState == 3)
                    {
                        if (rawSelectionBox)
                        {
                            // EditorDirector raises troopSelectionBoxOn for
                            // every 3+ px mouse-up after CurrentAction 8, while
                            // TroopSelector only establishes a real selection
                            // rectangle above 16 px. Preserve the owned native
                            // 1 -> 2 -> 3 direct-click gesture by normalising
                            // only that narrow minor-drag token before
                            // preDLLCallActions reads it as selection_on.
                            owner._nativeSelectionBoxField.SetValue(
                                __instance,
                                false);
                            int gestureUnitId = owner._pendingSelectionWorkerId > 0
                                ? owner._pendingSelectionWorkerId
                                : owner._directClickGestureUnitId;
                            string normalizationKey =
                                "native_direct_click_minor_drag."
                                + gestureUnitId.ToString(
                                    CultureInfo.InvariantCulture);
                            if (owner._evidenceLogged.Add(normalizationKey))
                            {
                                owner._info(
                                    "Worker militia normalized EditorDirector's "
                                    + "minor direct-click drag token before the "
                                    + "native mouse-up: unit_id="
                                    + gestureUnitId.ToString(
                                        CultureInfo.InvariantCulture)
                                    + " delta_x=" + selectionDeltaX.ToString(
                                        "0.0",
                                        CultureInfo.InvariantCulture)
                                    + " delta_y=" + selectionDeltaY.ToString(
                                        "0.0",
                                        CultureInfo.InvariantCulture) + ".");
                            }
                        }
                        if (owner._pendingSelectionWorkerId > 0
                            && owner._directClickGestureUnitId
                                == owner._pendingSelectionWorkerId
                            && !owner._pendingSelectionCancellationRequested)
                        {
                            // CurrentAction 8 replaces selectedChimpList on
                            // every held/raised frame. Refresh only the same
                            // owned singleton so DLL_TroopSelection sees one
                            // coherent candidate at the concluding mouse-up.
                            owner.InjectNativeSelectionCandidate(
                                __instance,
                                owner._pendingSelectionWorkerId);
                        }
                        owner.CompleteNativeDirectClick(hovered);
                    }
                    else if (owner._pendingSelectionWorkerId > 0
                        && owner._directClickGestureUnitId
                            == owner._pendingSelectionWorkerId
                        && !owner._pendingSelectionCancellationRequested)
                    {
                        // A 3+ px minor drag changes CurrentAction to 8 and
                        // EditorDirector overwrites the injected arrays during
                        // state 2. Reassert the same candidate; this is not a
                        // second click/scheduler request.
                        owner.InjectNativeSelectionCandidate(
                            __instance,
                            owner._pendingSelectionWorkerId);
                    }
                }
                else if (!capturedRightEdge
                    && ((nativeMouseState >= 1 && nativeMouseState <= 3)
                        || boxSelection))
                {
                    owner.SuppressNativeSelectionForCycle(__instance);
                }
                if (neutralizeConfirmedGesture)
                {
                    // A click on the already-confirmed worker is a managed
                    // selection no-op for the whole 1 -> 2 -> 3 gesture. Do
                    // not let any of those phases toggle the native singleton.
                    __result = 0;
                }
                if (capturedRightDown)
                {
                    owner.BeginRightClickGesture(
                        hovered,
                        hasGroundDestination,
                        mapMouse.x,
                        mapMouse.y,
                        nativeMouseState,
                        capturedRightUp);
                }
                if (capturedRightUp)
                {
                    // Mouse-up only confirms the stored down target/centre.
                    // Promotion waits for this DLL_RunTick's postfix so the
                    // native command and UnitMoveHere callback always win.
                    owner.CompleteRightClickGesture(
                        nativeMouseState,
                        capturedRightDown);
                }
                if (leftCommandDown)
                {
                    // Reuse the hardened command-gesture machinery; the packet
                    // is button-agnostic and carries the worker + ground/enemy
                    // target. A left click delivers down and up in separate
                    // native calls, so this only captures here.
                    owner.BeginRightClickGesture(
                        hovered,
                        leftGroundDestination,
                        mapMouse.x,
                        mapMouse.y,
                        nativeMouseState,
                        false);
                    if (owner._evidenceLogged.Add("left_command_captured"))
                    {
                        owner._info(
                            "Worker militia captured a left-click command "
                            + "(classic controls): the selected worker stays "
                            + "selected and the move/attack is issued through "
                            + "the mission path.");
                    }
                }
                if (leftCommandUp)
                {
                    owner.CompleteRightClickGesture(nativeMouseState, false);
                }
                }
            }
            catch (Exception exception)
            {
                __result = vanillaResult;
                rightDown = vanillaRightDown;
                rightUp = vanillaRightUp;
                lock (owner._gate)
                {
                    owner.ContainOrdinaryEventFailure(
                        "native mouse packet",
                        exception,
                        true);
                }
            }
        }

        private bool IsGenuineNativeSelectionBox(
            EditorDirector director,
            bool rawSelectionBox,
            out float deltaX,
            out float deltaY)
        {
            deltaX = 0f;
            deltaY = 0f;
            if (TroopSelector.instance != null
                && TroopSelector.instance.selection_established)
            {
                return true;
            }
            if (!rawSelectionBox || director == null)
            {
                return false;
            }
            var start = (UnityEngine.Vector2)_nativeSelectionStartField.GetValue(
                director);
            var current =
                (UnityEngine.Vector2)_nativeSelectionCurrentField.GetValue(
                    director);
            deltaX = UnityEngine.Mathf.Abs(current.x - start.x);
            deltaY = UnityEngine.Mathf.Abs(current.y - start.y);
            if (start.x < 0f
                || float.IsNaN(deltaX)
                || float.IsNaN(deltaY)
                || float.IsInfinity(deltaX)
                || float.IsInfinity(deltaY))
            {
                // Unknown geometry remains a real box token fail-closed. Only
                // a pinned, finite sub-threshold gesture is normalised.
                return true;
            }
            return deltaX > NativeSelectionBoxThresholdPixels
                || deltaY > NativeSelectionBoxThresholdPixels;
        }

        private static bool NativeRunPrefix()
        {
            WorkerMilitiaFeature owner;
            lock (InputOwnerGate)
            {
                owner = _inputOwner;
            }
            if (owner == null)
            {
                return true;
            }
            try
            {
                return owner.ValidateCommandClassLeaseBeforeNativeRun();
            }
            catch (Exception exception)
            {
                lock (owner._gate)
                {
                    owner.FailCommandClassLeaseLocked(
                        "native-run prefix validation threw "
                            + exception.GetType().Name,
                        true,
                        true);
                }
                return false;
            }
        }

        private static void NativeRunPostfix(bool __runOriginal)
        {
            WorkerMilitiaFeature owner;
            lock (InputOwnerGate)
            {
                owner = _inputOwner;
            }
            if (owner != null)
            {
                try
                {
                    if (__runOriginal)
                    {
                        try
                        {
                            owner.ObserveAndReplayCommandCursor();
                        }
                        catch (Exception)
                        {
                            // Cursor cosmetics must never disturb the engine tick.
                        }
                        owner.CompleteNativeRun();
                    }
                }
                finally
                {
                    owner.EndNativeRunTransaction();
                }
            }
        }

        private static Exception NativeRunFinalizer(Exception __exception)
        {
            WorkerMilitiaFeature owner;
            lock (InputOwnerGate)
            {
                owner = _inputOwner;
            }
            if (owner != null)
            {
                owner.EndNativeRunTransaction();
            }
            return __exception;
        }

        private static void NativeSelectedTroopsPrefix(
            EngineInterface.PlayState gameState,
            ref bool inTroopUI)
        {
            WorkerMilitiaFeature owner;
            lock (InputOwnerGate)
            {
                owner = _inputOwner;
            }
            if (owner == null
                || !owner._mapApplied
                || owner._networkSuppressed
                || owner._selectionQuarantineSuppressed
                || gameState == null)
            {
                return;
            }
            bool vanillaInTroopUi = inTroopUI;
            try
            {
                bool nativeInTroopUI = vanillaInTroopUi;
                if (!owner.IsLeasedMilitiaSingleton(gameState))
                {
                    return;
                }
                bool managedOverride = !nativeInTroopUI;
                owner.LogManagedSelectionGateTelemetry(
                    gameState,
                    nativeInTroopUI,
                    managedOverride);
                if (nativeInTroopUI)
                {
                    return;
                }
                // updateDLLSelectedTroops already owns the main-thread
                // managed selection lifecycle. Only open its existing troop
                // gate for the verified native singleton; do not invoke UI
                // actions from the simulation-thread DLL_RunTick postfix.
                inTroopUI = true;
            }
            catch (Exception exception)
            {
                inTroopUI = vanillaInTroopUi;
                lock (owner._gate)
                {
                    owner.ContainOrdinaryEventFailure(
                        "managed militia troop-selection gate",
                        exception,
                        true);
                }
            }
        }

        private bool HasOutstandingNativeSelection()
        {
            lock (_gate)
            {
                return _pendingSelectionWorkerId > 0
                    && _selectionLease != null;
            }
        }

        /// <summary>
        /// True when a militia worker is the settled, confirmed native
        /// singleton this feature owns and can therefore be commanded by a
        /// left-click. Excludes any in-progress selection or direct-click
        /// gesture so a command never races selection.
        /// </summary>
        private bool HasConfirmedCommandableMilitia(out int workerId)
        {
            workerId = 0;
            if (_nativeSelectionLifecycle != NativeSelectionLifecycle.Confirmed
                || _pendingSelectionWorkerId > 0
                || _directClickGestureUnitId > 0
                || _selectedWorkerId <= 0
                || _selectionLease == null
                || _selectionLease.UnitId != _selectedWorkerId)
            {
                return false;
            }
            if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    _selectedWorkerId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            // Identitaet, nicht Beschaeftigung: der Befehlskegel haengt
            // nicht daran, ob die Huette des Arbeiters noch steht.
            if (!SelectionLeaseIdentityMatches(_selectionLease, ref unit)
                || !IsNativeSingletonSelection(_selectedWorkerId))
            {
                return false;
            }
            workerId = _selectedWorkerId;
            return true;
        }

        private bool IsEnemyOfLocalPlayer(int unitId)
        {
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (unitId <= 0 || units == null || !units.IsValid(unitId))
            {
                return false;
            }
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            return IsEnemyPlayerUnit(localPlayer, units.GetOwner(unitId));
        }

        private bool HasActiveNativeDirectClickGesture()
        {
            lock (_gate)
            {
                return _directClickGestureUnitId > 0;
            }
        }

        private bool IsConfirmedNativeDirectClickNoOp()
        {
            lock (_gate)
            {
                return _confirmedSelectionGestureNoOp
                    && _directClickGestureUnitId > 0
                    && _pendingSelectionWorkerId == 0
                    && _nativeSelectionLifecycle
                        == NativeSelectionLifecycle.Confirmed;
            }
        }

        private bool TryBeginNativeDirectClick(
            EditorDirector director,
            int unitId)
        {
            lock (_gate)
            {
                if (!IsOperationalLocked()
                    || _nativeSelectionDisabledForProcess)
                {
                    return false;
                }
                NativeSelectionLease current = _selectionLease;
                if (_pendingSelectionWorkerId > 0)
                {
                    // Chore 0x48 has no proved cancellation primitive. A
                    // repeated click must neither replay the packet nor renew
                    // its deadline; a different worker cannot take ownership
                    // until the old chore has either committed and been
                    // removed or the process/map has been abandoned.
                    if (current == null || current.UnitId != unitId)
                    {
                        RequestOutstandingSelectionCancellation(
                            "different worker clicked while native selection was pending",
                            false,
                            false);
                    }
                    return true;
                }
                if (_selectedWorkerId == unitId
                    && current != null
                    && current.UnitId == unitId)
                {
                    _directClickGestureUnitId = unitId;
                    _confirmedSelectionGestureNoOp = true;
                    return true;
                }
                if (current != null)
                {
                    DeselectOwnedMilitia("different worker selected");
                    ReleaseNativeSelection("different worker selected");
                }
                if (!TryArmNativeSelection(unitId))
                {
                    return false;
                }
                InjectNativeSelectionCandidate(director, unitId);
                _pendingSelectionWorkerId = unitId;
                _directClickGestureUnitId = unitId;
                _confirmedSelectionGestureNoOp = false;
                _nativeSelectionPacketInFlight = true;
                _directSelectionMouseUpAccepted = false;
                _pendingSelectionCancellationRequested = false;
                _pendingSelectionIdentityInvalidated = false;
                _pendingSelectionCancellationReason = null;
                _nativeSelectionLifecycle =
                    NativeSelectionLifecycle.PacketInjected;
                _directSelectionDeadlineTick = unchecked(
                    SimulationNowMilliseconds()
                    + NativeSelectionVerificationMilliseconds);
                return true;
            }
        }

        private void CompleteNativeDirectClick(int hoveredUnitId)
        {
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                int gestureUnitId = _directClickGestureUnitId;
                bool confirmedNoOp = _confirmedSelectionGestureNoOp;
                _directClickGestureUnitId = 0;
                _confirmedSelectionGestureNoOp = false;
                if (confirmedNoOp)
                {
                    return;
                }
                if (gestureUnitId <= 0 || lease == null)
                {
                    return;
                }
                if (hoveredUnitId != gestureUnitId
                    || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                        hoveredUnitId,
                        out var pointer))
                {
                    if (_pendingSelectionWorkerId > 0)
                    {
                        RequestOutstandingSelectionCancellation(
                            "direct-click mouse-up changed unit",
                            false,
                            false);
                    }
                    else
                    {
                        DeselectOwnedMilitia(
                            "direct-click mouse-up changed unit");
                        ReleaseNativeSelection(
                            "direct-click mouse-up changed unit");
                    }
                    return;
                }
                ref GameUnit unit = ref pointer.AsRef();
                // Identitaet, nicht Beschaeftigung - der Zweig darunter setzt
                // _nativeSelectionDisabledForProcess.
                if (!SelectionLeaseIdentityMatches(lease, ref unit))
                {
                    if (_pendingSelectionWorkerId > 0)
                    {
                        RequestOutstandingSelectionCancellation(
                            "direct-click mouse-up changed unit identity",
                            true,
                            true);
                    }
                    else
                    {
                        EndCommandClassLease(
                            lease,
                            "direct-click mouse-up changed unit identity");
                        _selectionLease = null;
                        _selectedWorkerId = 0;
                        _nativeSelectionDisabledForProcess = true;
                        if (!_nativeCommandClassUnavailableForProcess)
                        {
                            _selectionQuarantineSuppressed = true;
                        }
                        _nativeSelectionLifecycle =
                            NativeSelectionLifecycle.Quarantined;
                    }
                    return;
                }
                if (_pendingSelectionWorkerId <= 0)
                {
                    // Re-click/hold/up on an already confirmed militia unit is
                    // one direct gesture, not a box/other-selection input.
                    return;
                }
                _directSelectionMouseUpAccepted = true;
            }
        }

        private void CancelNativeDirectClickGesture(
            EditorDirector director,
            string reason,
            bool identityInvalidated)
        {
            lock (_gate)
            {
                _directClickGestureUnitId = 0;
                _confirmedSelectionGestureNoOp = false;
                if (_pendingSelectionWorkerId > 0)
                {
                    RequestOutstandingSelectionCancellation(
                        reason,
                        identityInvalidated,
                        identityInvalidated);
                    return;
                }
                SuppressNativeSelectionForCycle(director);
            }
        }

        private void RequestOutstandingSelectionCancellation(
            string reason,
            bool identityInvalidated,
            bool disableForProcess)
        {
            lock (_gate)
            {
                if (_pendingSelectionWorkerId <= 0
                    || _selectionLease == null)
                {
                    return;
                }
                FilterWorkerFromNativeSelectionPacket(
                    EditorDirector.instance,
                    _selectionLease.UnitId);
                // Keep the observer lease until the possible late native chore
                // has settled, but close executable-memory scope immediately.
                // A cancelled transaction no longer owns a commandable worker,
                // regardless of whether the unit identity itself is intact.
                EndCommandClassLease(_selectionLease, reason);
                _nativeSelectionPacketInFlight = false;
                _directClickGestureUnitId = 0;
                _confirmedSelectionGestureNoOp = false;
                _directSelectionMouseUpAccepted = false;
                _pendingSelectionCancellationRequested = true;
                _pendingSelectionIdentityInvalidated |= identityInvalidated;
                _nativeSelectionDisabledForProcess |= disableForProcess;
                if ((identityInvalidated || disableForProcess)
                    && !_nativeCommandClassUnavailableForProcess)
                {
                    _selectionQuarantineSuppressed = true;
                }
                _pendingSelectionCancellationReason = reason;
                _selectedWorkerId = 0;
                _nativeSelectionLifecycle = identityInvalidated
                    || disableForProcess
                        ? NativeSelectionLifecycle.Quarantined
                        : NativeSelectionLifecycle.CancelAwaitingCommit;
                string evidenceKey = "native_selection_cancel_pending."
                    + reason;
                if (_evidenceLogged.Add(evidenceKey))
                {
                    _warning(
                        "Worker militia quarantined an unstornierable native "
                        + "selection request during " + reason
                        + "; its lease remains owned until authoritative "
                        + "native output can be removed exactly.");
                }
            }
        }

        private bool IsLeasedMilitiaSingleton(
            EngineInterface.PlayState gameState)
        {
            if (gameState.numSelectedChimps != 1
                || gameState.selectedChimps == null
                || gameState.selectedChimps.Length < 1)
            {
                return false;
            }
            int unitId = gameState.selectedChimps[0];
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                if (!IsOperationalLocked()
                    || unitId <= 0
                    || lease == null
                    || _selectedWorkerId != unitId
                    || _pendingSelectionWorkerId != 0
                    || _nativeSelectionLifecycle
                        != NativeSelectionLifecycle.Confirmed
                    || lease.TemporarilySuppressed
                    || lease.UnitId != unitId
                    || !IsMilitia(lease.Type))
                {
                    return false;
                }
                GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
                if (units == null
                    || players == null
                    || !units.TryGetUnitByIdEx(unitId, out var pointer))
                {
                    return false;
                }
                ref GameUnit unit = ref pointer.AsRef();
                int localPlayer = players.GetLocalPlayerId();
                if (localPlayer <= 0
                    || lease.Owner != localPlayer
                    || unit.r_AliveState != AliveState.IsAlive
                    // Identitaet, nicht Beschaeftigung - siehe oben.
                    || !SelectionLeaseIdentityMatches(lease, ref unit)
                    || unit.r_UnitHover != 1
                    || unit.r_UnitSelected != lease.Owner
                    || SeInteropFieldAliases.CommandMode(ref unit) != 1)
                {
                    return false;
                }
                return true;
            }
        }

        private void LogManagedSelectionGateTelemetry(
            EngineInterface.PlayState gameState,
            bool nativeInTroopUI,
            bool managedOverride)
        {
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                int selectedId = gameState.selectedChimps != null
                        && gameState.selectedChimps.Length > 0
                    ? gameState.selectedChimps[0]
                    : 0;
                if (lease == null
                    || lease.ManagedGateTelemetryLogged
                    || lease.UnitId != selectedId)
                {
                    return;
                }
                lease.ManagedGateTelemetryLogged = true;
                int currentThreadId = Thread.CurrentThread.ManagedThreadId;
                _info(
                    "Worker militia managed selection gate telemetry: unit="
                    + UnitName(lease.Type) + " unit_id="
                    + lease.UnitId.ToString(CultureInfo.InvariantCulture)
                    + " global_id="
                    + lease.GlobalId.ToString(CultureInfo.InvariantCulture)
                    + " native_in_troop_ui="
                    + TelemetryBoolean(nativeInTroopUI)
                    + " managed_override="
                    + TelemetryBoolean(managedOverride)
                    + " app_mode="
                    + gameState.app_mode.ToString(CultureInfo.InvariantCulture)
                    + " app_sub_mode="
                    + gameState.app_sub_mode.ToString(
                        CultureInfo.InvariantCulture)
                    + " in_chimp="
                    + gameState.in_chimp.ToString(CultureInfo.InvariantCulture)
                    + " in_chimp_type="
                    + gameState.in_chimp_type.ToString(
                        CultureInfo.InvariantCulture)
                    + " selected_count="
                    + gameState.numSelectedChimps.ToString(
                        CultureInfo.InvariantCulture)
                    + " selected_id="
                    + selectedId.ToString(CultureInfo.InvariantCulture)
                    + " lord_only="
                    + gameState.lordOnlySelected.ToString(
                        CultureInfo.InvariantCulture)
                    + " current_thread="
                    + currentThreadId.ToString(CultureInfo.InvariantCulture)
                    + " main_thread="
                    + _mainThreadId.ToString(CultureInfo.InvariantCulture)
                    + " thread_match="
                    + TelemetryBoolean(
                        _mainThreadId > 0
                        && currentThreadId == _mainThreadId) + ".");
            }
        }

        private void LogRightClickGesture(
            string phase,
            long generation,
            string status,
            string reason,
            int workerId,
            int nativeMouseState,
            bool rightDown,
            bool rightUp,
            int hoveredUnitId,
            bool groundValid,
            int groundX,
            int groundY)
        {
            _info(
                RuntimeLogContract.WorkerMilitiaRightClickTelemetry(
                    phase,
                    generation,
                    status,
                    reason,
                    workerId,
                    nativeMouseState,
                    rightDown,
                    rightUp,
                    hoveredUnitId,
                    groundValid,
                    groundX,
                    groundY,
                    _nativeMoveSequence));
        }

        private bool TryCaptureCommandableSelection(
            InputPacket packet,
            out string rejectionReason)
        {
            lock (_gate)
            {
                int unitId = _selectedWorkerId;
                NativeSelectionLease lease = _selectionLease;
                if (packet == null)
                {
                    rejectionReason = "packet_null";
                    return false;
                }
                if (unitId <= 0)
                {
                    rejectionReason = "managed_selection_missing";
                    return false;
                }
                if (lease == null)
                {
                    rejectionReason = "selection_lease_missing";
                    return false;
                }
                if (lease.UnitId != unitId)
                {
                    rejectionReason = "selection_lease_mismatch";
                    return false;
                }
                if (!IsNativeSingletonSelection(unitId))
                {
                    rejectionReason = "native_singleton_missing";
                    return false;
                }
                if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                        unitId,
                        out var pointer))
                {
                    rejectionReason = "worker_slot_missing";
                    return false;
                }
                ref GameUnit unit = ref pointer.AsRef();
                // Identitaet, nicht Beschaeftigung: ein Jaeger, dessen
                // Huette abgebrannt ist, bleibt befehligbar. Das ist der Zweck
                // des Mods, nicht sein Fehlerfall.
                if (!SelectionLeaseIdentityMatches(lease, ref unit))
                {
                    rejectionReason = "worker_identity_changed";
                    return false;
                }
                if (unit.r_AliveState != AliveState.IsAlive)
                {
                    rejectionReason = "worker_not_alive";
                    return false;
                }
                if (unit.r_UnitSelected != lease.Owner)
                {
                    rejectionReason = "selection_owner_changed";
                    return false;
                }
                packet.SelectedWorkerId = unitId;
                packet.SelectedWorkerGlobalId = lease.GlobalId;
                packet.SelectedWorkerOwner = lease.Owner;
                packet.SelectedWorkerType = lease.Type;
                rejectionReason = "none";
                return true;
            }
        }

        private void BeginRightClickGesture(
            int hoveredUnitId,
            bool hasGroundDestination,
            int groundDestinationX,
            int groundDestinationY,
            int nativeMouseState,
            bool rightUpAtDown)
        {
            lock (_gate)
            {
                long generation = unchecked(++_rightClickGestureGeneration);
                if (!IsOperationalLocked())
                {
                    _pendingRightClickGesture = null;
                    LogRightClickGesture(
                        "down",
                        generation,
                        "rejected",
                        "feature_not_operational",
                        _selectedWorkerId,
                        nativeMouseState,
                        true,
                        rightUpAtDown,
                        hoveredUnitId,
                        hasGroundDestination,
                        groundDestinationX,
                        groundDestinationY);
                    return;
                }
                var packet = new InputPacket
                {
                    RightDown = true,
                    HasGroundDestination = hasGroundDestination,
                    GroundDestinationX = groundDestinationX,
                    GroundDestinationY = groundDestinationY,
                    NativeMoveSequenceAtCapture = _nativeMoveSequence,
                };
                if (!TryCaptureCommandableSelection(
                        packet,
                        out string rejectionReason))
                {
                    _pendingRightClickGesture = null;
                    LogRightClickGesture(
                        "down",
                        generation,
                        "rejected",
                        rejectionReason,
                        _selectedWorkerId,
                        nativeMouseState,
                        true,
                        rightUpAtDown,
                        hoveredUnitId,
                        hasGroundDestination,
                        groundDestinationX,
                        groundDestinationY);
                    return;
                }
                // rightDownForEngine is an edge flag which the managed getter
                // consumes and clears. A second down therefore starts a new
                // gesture; discard an older missing-up gesture without ever
                // promoting its stale target.
                _pendingRightClickGesture = null;
                UnitSnapshot target = CaptureUnit(hoveredUnitId);
                if (target != null
                    && IsEnemyPlayerUnit(
                        packet.SelectedWorkerOwner,
                        target.Owner))
                {
                    packet.HoveredUnitId = target.Id;
                    packet.HoveredUnitGlobalId = target.GlobalId;
                    packet.HoveredUnitOwner = target.Owner;
                    packet.HoveredUnitType = target.Type;
                }
                string captureReason = packet.HoveredUnitId > 0
                    ? "enemy_target"
                    : hasGroundDestination
                        ? "ground_destination"
                        : "native_only";
                _pendingRightClickGesture = new RightClickGesture
                {
                    Generation = generation,
                    Packet = packet,
                    DeadlineTick = unchecked(
                        SimulationNowMilliseconds()
                        + RightClickGestureTimeoutMilliseconds),
                    HoveredUnitIdAtDown = hoveredUnitId,
                    NativeMouseStateAtDown = nativeMouseState,
                    NativeMouseStateAtUp = -1,
                    Released = false,
                };
                LogRightClickGesture(
                    "down",
                    generation,
                    "captured",
                    captureReason,
                    packet.SelectedWorkerId,
                    nativeMouseState,
                    true,
                    rightUpAtDown,
                    hoveredUnitId,
                    hasGroundDestination,
                    groundDestinationX,
                    groundDestinationY);
                _info(
                    "Worker militia native snapshot at right-click down: gesture="
                    + generation.ToString(CultureInfo.InvariantCulture)
                    + " unit_id="
                    + packet.SelectedWorkerId.ToString(CultureInfo.InvariantCulture)
                    + " " + DescribeNativeSelectionGlobals() + ".");
            }
        }

        private void CompleteRightClickGesture(
            int nativeMouseState,
            bool rightDownAtUp)
        {
            lock (_gate)
            {
                RightClickGesture gesture = _pendingRightClickGesture;
                if (gesture == null)
                {
                    LogRightClickGesture(
                        "up",
                        0,
                        "rejected",
                        "matching_down_missing",
                        _selectedWorkerId,
                        nativeMouseState,
                        rightDownAtUp,
                        true,
                        0,
                        false,
                        0,
                        0);
                    return;
                }
                InputPacket packet = gesture.Packet;
                int now = SimulationNowMilliseconds();
                if (HasReached(now, gesture.DeadlineTick))
                {
                    _pendingRightClickGesture = null;
                    LogRightClickGesture(
                        "up",
                        gesture.Generation,
                        "rejected",
                        "gesture_deadline_expired",
                        packet == null ? 0 : packet.SelectedWorkerId,
                        nativeMouseState,
                        rightDownAtUp,
                        true,
                        gesture.HoveredUnitIdAtDown,
                        packet != null && packet.HasGroundDestination,
                        packet == null ? 0 : packet.GroundDestinationX,
                        packet == null ? 0 : packet.GroundDestinationY);
                    return;
                }
                if (gesture.SelectionLostAfterCapture)
                {
                    // The native selection is gone by the engine's own doing
                    // (see ReleaseNativeSelection); the captured packet is the
                    // identity contract for this click. Complete it when that
                    // exact worker is still alive and ours, never against a
                    // reused slot.
                    bool sameWorker = packet != null
                        && RightClickGestureWorkerStillMatches(packet);
                    if (!sameWorker)
                    {
                        _pendingRightClickGesture = null;
                    }
                    else
                    {
                        gesture.NativeMouseStateAtUp = nativeMouseState;
                        gesture.Released = true;
                    }
                    LogRightClickGesture(
                        "up",
                        gesture.Generation,
                        sameWorker ? "released" : "rejected",
                        sameWorker
                            ? "matching_mouse_up_after_native_deselection"
                            : "worker_identity_changed_after_native_deselection",
                        packet == null ? 0 : packet.SelectedWorkerId,
                        nativeMouseState,
                        rightDownAtUp,
                        true,
                        gesture.HoveredUnitIdAtDown,
                        packet != null && packet.HasGroundDestination,
                        packet == null ? 0 : packet.GroundDestinationX,
                        packet == null ? 0 : packet.GroundDestinationY);
                    return;
                }
                var current = new InputPacket();
                if (!TryCaptureCommandableSelection(
                        current,
                        out string rejectionReason))
                {
                    _pendingRightClickGesture = null;
                    LogRightClickGesture(
                        "up",
                        gesture.Generation,
                        "rejected",
                        rejectionReason,
                        packet == null ? 0 : packet.SelectedWorkerId,
                        nativeMouseState,
                        rightDownAtUp,
                        true,
                        gesture.HoveredUnitIdAtDown,
                        packet != null && packet.HasGroundDestination,
                        packet == null ? 0 : packet.GroundDestinationX,
                        packet == null ? 0 : packet.GroundDestinationY);
                    return;
                }
                if (packet == null)
                {
                    _pendingRightClickGesture = null;
                    LogRightClickGesture(
                        "up",
                        gesture.Generation,
                        "rejected",
                        "gesture_packet_missing",
                        current.SelectedWorkerId,
                        nativeMouseState,
                        rightDownAtUp,
                        true,
                        gesture.HoveredUnitIdAtDown,
                        false,
                        0,
                        0);
                    return;
                }
                if (current.SelectedWorkerId
                        != packet.SelectedWorkerId
                    || current.SelectedWorkerGlobalId
                        != packet.SelectedWorkerGlobalId
                    || current.SelectedWorkerOwner
                        != packet.SelectedWorkerOwner
                    || current.SelectedWorkerType
                        != packet.SelectedWorkerType)
                {
                    _pendingRightClickGesture = null;
                    LogRightClickGesture(
                        "up",
                        gesture.Generation,
                        "rejected",
                        "selected_worker_changed",
                        current.SelectedWorkerId,
                        nativeMouseState,
                        rightDownAtUp,
                        true,
                        gesture.HoveredUnitIdAtDown,
                        packet.HasGroundDestination,
                        packet.GroundDestinationX,
                        packet.GroundDestinationY);
                    return;
                }
                gesture.NativeMouseStateAtUp = nativeMouseState;
                gesture.Released = true;
                LogRightClickGesture(
                    "up",
                    gesture.Generation,
                    "released",
                    "matching_mouse_up",
                    packet.SelectedWorkerId,
                    nativeMouseState,
                    rightDownAtUp,
                    true,
                    gesture.HoveredUnitIdAtDown,
                    packet.HasGroundDestination,
                    packet.GroundDestinationX,
                    packet.GroundDestinationY);
            }
        }

        private void PromoteReleasedRightClickGestureAfterNativeRun()
        {
            lock (_gate)
            {
                RightClickGesture gesture = _pendingRightClickGesture;
                if (gesture == null)
                {
                    return;
                }
                int now = SimulationNowMilliseconds();
                if (HasReached(now, gesture.DeadlineTick))
                {
                    _pendingRightClickGesture = null;
                    InputPacket expiredPacket = gesture.Packet;
                    LogRightClickGesture(
                        "promotion",
                        gesture.Generation,
                        "rejected",
                        gesture.Released
                            ? "post_run_deadline_expired"
                            : "mouse_up_timeout",
                        expiredPacket == null
                            ? 0
                            : expiredPacket.SelectedWorkerId,
                        gesture.Released
                            ? gesture.NativeMouseStateAtUp
                            : gesture.NativeMouseStateAtDown,
                        false,
                        false,
                        gesture.HoveredUnitIdAtDown,
                        expiredPacket != null
                            && expiredPacket.HasGroundDestination,
                        expiredPacket == null
                            ? 0
                            : expiredPacket.GroundDestinationX,
                        expiredPacket == null
                            ? 0
                            : expiredPacket.GroundDestinationY);
                    return;
                }
                if (!gesture.Released)
                {
                    return;
                }
                _pendingRightClickGesture = null;
                if (!IsOperationalLocked()
                    || _deferredFailure != null
                    || gesture.Packet == null)
                {
                    string rejectionReason = !IsOperationalLocked()
                        ? "feature_not_operational"
                        : _deferredFailure != null
                            ? "deferred_failure"
                            : "gesture_packet_missing";
                    InputPacket rejectedPacket = gesture.Packet;
                    LogRightClickGesture(
                        "promotion",
                        gesture.Generation,
                        "rejected",
                        rejectionReason,
                        rejectedPacket == null
                            ? 0
                            : rejectedPacket.SelectedWorkerId,
                        gesture.NativeMouseStateAtUp,
                        false,
                        false,
                        gesture.HoveredUnitIdAtDown,
                        rejectedPacket != null
                            && rejectedPacket.HasGroundDestination,
                        rejectedPacket == null
                            ? 0
                            : rejectedPacket.GroundDestinationX,
                        rejectedPacket == null
                            ? 0
                            : rejectedPacket.GroundDestinationY);
                    return;
                }
                // This runs only in EngineInterface.run's postfix. A native
                // UnitMoveHere Post may have happened on the earlier down run,
                // before Released became true; its observed/accepted result is
                // carried by this exact packet to the later main-thread commit.
                EnqueueInput(gesture.Packet);
                LogRightClickGesture(
                    "promotion",
                    gesture.Generation,
                    "promoted",
                    "post_native_run",
                    gesture.Packet.SelectedWorkerId,
                    gesture.NativeMouseStateAtUp,
                    false,
                    false,
                    gesture.HoveredUnitIdAtDown,
                    gesture.Packet.HasGroundDestination,
                    gesture.Packet.GroundDestinationX,
                    gesture.Packet.GroundDestinationY);
            }
        }

        private void DiscardExpiredRightClickGesture(int now)
        {
            RightClickGesture gesture = _pendingRightClickGesture;
            if (gesture != null && HasReached(now, gesture.DeadlineTick))
            {
                _pendingRightClickGesture = null;
                InputPacket packet = gesture.Packet;
                LogRightClickGesture(
                    "promotion",
                    gesture.Generation,
                    "rejected",
                    gesture.Released
                        ? "post_run_deadline_expired"
                        : "mouse_up_timeout",
                    packet == null ? 0 : packet.SelectedWorkerId,
                    gesture.Released
                        ? gesture.NativeMouseStateAtUp
                        : gesture.NativeMouseStateAtDown,
                    false,
                    false,
                    gesture.HoveredUnitIdAtDown,
                    packet != null && packet.HasGroundDestination,
                    packet == null ? 0 : packet.GroundDestinationX,
                    packet == null ? 0 : packet.GroundDestinationY);
            }
        }

        private void InjectNativeSelectionCandidate(
            EditorDirector director,
            int unitId)
        {
            var singleton = new[] { unitId };
            _nativeSelectedChimpListField.SetValue(director, singleton);
            _nativeUnderCursorChimpListField.SetValue(director, singleton);
            _nativeGotNewSelectionInfoField.SetValue(director, true);
            if (_evidenceLogged.Add("native_candidate." + unitId.ToString(
                    CultureInfo.InvariantCulture)))
            {
                _info(
                    "Worker militia injected the direct-click singleton into "
                    + "both selectedChimps and underCursorChimps for the native "
                    + "DLL_TroopSelection state machine: unit_id="
                    + unitId.ToString(CultureInfo.InvariantCulture) + ".");
            }
        }

        private void FilterWorkerFromNativeSelectionPacket(
            EditorDirector director,
            int workerUnitId)
        {
            if (director == null || workerUnitId <= 0)
            {
                return;
            }
            int[] selected = FilterNativeSelectionList(
                _nativeSelectedChimpListField.GetValue(director) as int[],
                workerUnitId);
            int[] underCursor = FilterNativeSelectionList(
                _nativeUnderCursorChimpListField.GetValue(director) as int[],
                workerUnitId);
            int[] lastSelected = FilterNativeSelectionList(
                _nativeLastSelectedChimpListField.GetValue(director) as int[],
                workerUnitId);
            _nativeSelectedChimpListField.SetValue(director, selected);
            _nativeUnderCursorChimpListField.SetValue(director, underCursor);
            _nativeLastSelectedChimpListField.SetValue(director, lastSelected);
            // The packet now deliberately differs from last frame. Prevent
            // preDLLCallActions from replacing the filtered current candidate
            // with its unfiltered replay list before DLL_TroopSelection.
            _nativeGotNewSelectionInfoField.SetValue(director, true);
        }

        private static int[] FilterNativeSelectionList(
            int[] source,
            int workerUnitId)
        {
            if (source == null || source.Length == 0)
            {
                return new int[0];
            }
            int retained = 0;
            for (int index = 0; index < source.Length; index++)
            {
                if (source[index] != workerUnitId)
                {
                    retained++;
                }
            }
            if (retained == source.Length)
            {
                return source;
            }
            var filtered = new int[retained];
            int destination = 0;
            for (int index = 0; index < source.Length; index++)
            {
                int unitId = source[index];
                if (unitId != workerUnitId)
                {
                    filtered[destination++] = unitId;
                }
            }
            return filtered;
        }

        private void ClearInjectedNativeSelectionCandidate(
            EditorDirector director)
        {
            if (director == null)
            {
                return;
            }
            var empty = new int[0];
            _nativeSelectedChimpListField.SetValue(director, empty);
            _nativeUnderCursorChimpListField.SetValue(director, empty);
            _nativeLastSelectedChimpListField.SetValue(director, empty);
            // preDLLCallActions otherwise restores selectedChimpList from
            // lastSelectedChimpList before calling DLL_TroopSelection. Mark
            // this coherent empty packet as new so no stale worker singleton
            // can be replayed in the same cycle.
            _nativeGotNewSelectionInfoField.SetValue(director, true);
        }

        private static bool TroopsSelectedUiPrefix(
            MainViewModel __instance,
            bool fromInitialOpening)
        {
            WorkerMilitiaFeature owner;
            lock (InputOwnerGate)
            {
                owner = _inputOwner;
            }
            if (owner == null
                || !owner._mapApplied
                || owner._networkSuppressed
                || owner._selectionQuarantineSuppressed)
            {
                return true;
            }
            UiSelectionSnapshot selection;
            try
            {
                if (!owner.TryCaptureLeasedUiMilitia(out selection))
                {
                    // A native worker that is not backed by our exact live
                    // lease belongs to the game's ordinary information path.
                    return true;
                }
            }
            catch (Exception exception)
            {
                owner.LogMilitiaUiOriginalFallbackTelemetry(
                    null,
                    "entry_readback_exception",
                    exception);
                return true;
            }
            int currentThreadId = Thread.CurrentThread.ManagedThreadId;
            int mainThreadId = owner._mainThreadId;
            bool threadMatch = mainThreadId > 0
                && currentThreadId == mainThreadId;
            if (!threadMatch)
            {
                // Never mutate Noesis, and never let the original troop route
                // mutate it either, when an exact militia lease is delivered
                // on an unexpected thread. Ordinary/unleased workers already
                // returned through the original path above.
                owner.LogMilitiaUiThreadMismatchTelemetry(
                    selection,
                    fromInitialOpening,
                    currentThreadId,
                    mainThreadId);
                return false;
            }
            try
            {
                bool beforeMain = __instance.Show_HUD_Main;
                bool beforeTroops = __instance.Show_HUD_Troops;
                bool beforeBuilding = __instance.Show_HUD_Building;
                bool beforeControlGroups = __instance.Show_HUD_ControlGroups;
                // The simulation thread may settle a deselection after the
                // initial route decision. Re-read the complete native
                // singleton immediately before touching managed UI state.
                if (!owner.IsLeasedUiMilitiaSnapshotCurrent(selection))
                {
                    owner.LogMilitiaUiOriginalFallbackTelemetry(
                        selection,
                        "stale_before_mutation",
                        null);
                    return true;
                }
                // The worker portrait/name/comment panel lives in HUD_Buildings,
                // not HUD_Main. Keep that native worker information surface while
                // still suppressing HUD_Troops and its control-group strip.
                __instance.InBuildingGameAction();
                // Native troop selection changes app_sub_mode to the troop UI. Do
                // not let InBuildingGameAction infer its panel from that mode: the
                // worker information panel is the explicit mode-70 branch.
                __instance.setUpInbuilding(
                    70,
                    (int)selection.Type);
                __instance.Show_HUD_ControlGroups = false;
                owner.ApplyWorkerInformationUi(__instance, selection);
                // A stale mutation must never suppress the normal Lord/soldier
                // route. Returning true lets the original method normalize all
                // four HUD visibility properties after our partial write.
                if (!owner.IsLeasedUiMilitiaSnapshotCurrent(selection))
                {
                    owner.LogMilitiaUiOriginalFallbackTelemetry(
                        selection,
                        "stale_after_mutation",
                        null);
                    return true;
                }
                owner.LogMilitiaUiRouteTelemetry(
                    selection,
                    fromInitialOpening,
                    beforeMain,
                    beforeTroops,
                    beforeBuilding,
                    beforeControlGroups,
                    __instance.Show_HUD_Main,
                    __instance.Show_HUD_Troops,
                    __instance.Show_HUD_Building,
                    __instance.Show_HUD_ControlGroups,
                    currentThreadId,
                    mainThreadId);
                // The prefix only records the exact lease/view-model identity.
                // UI-tree evidence is read on a following persistent host Tick,
                // after the rest of this frame has had a chance to supersede it.
                owner.ScheduleMilitiaUiEvidence(
                    __instance,
                    selection,
                    fromInitialOpening);
                if (!owner.IsLeasedUiMilitiaSnapshotCurrent(selection))
                {
                    owner.LogMilitiaUiOriginalFallbackTelemetry(
                        selection,
                        "stale_before_original_suppression",
                        null);
                    return true;
                }
                return false;
            }
            catch (Exception exception)
            {
                // The original game method is the authoritative recovery path:
                // it rewrites the complete normal troop HUD even when one of the
                // managed worker-panel calls above failed after a partial write.
                owner.LogMilitiaUiOriginalFallbackTelemetry(
                    selection,
                    "mutation_exception",
                    exception);
                return true;
            }
        }

        private bool TryGetLeasedUiMilitia(
            out int selectedMilitia,
            out eChimps selectedType)
        {
            UiSelectionSnapshot selection;
            if (!TryCaptureLeasedUiMilitia(out selection))
            {
                selectedMilitia = 0;
                selectedType = (eChimps)0;
                return false;
            }
            selectedMilitia = selection.UnitId;
            selectedType = selection.Type;
            return true;
        }

        private bool TryCaptureLeasedUiMilitia(
            out UiSelectionSnapshot selection)
        {
            selection = null;
            int selectedMilitia = TryGetNativeSelectedMilitia();
            if (selectedMilitia <= 0)
            {
                return false;
            }
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
                if (!IsOperationalLocked()
                    || lease == null
                    || lease.TemporarilySuppressed
                    || lease.UnitId != selectedMilitia
                    || _selectedWorkerId != selectedMilitia
                    || _pendingSelectionWorkerId != 0
                    || _nativeSelectionLifecycle
                        != NativeSelectionLifecycle.Confirmed
                    || !IsMilitia(lease.Type)
                    || units == null
                    || players == null
                    || !units.TryGetUnitByIdEx(
                        selectedMilitia,
                        out var pointer))
                {
                    return false;
                }
                ref GameUnit unit = ref pointer.AsRef();
                int localPlayer = players.GetLocalPlayerId();
                if (localPlayer <= 0
                    || lease.Owner != localPlayer
                    || unit.r_AliveState != AliveState.IsAlive
                    // Identitaet, nicht Beschaeftigung - siehe oben.
                    || !SelectionLeaseIdentityMatches(lease, ref unit)
                    || unit.r_UnitHover != 1
                    || unit.r_UnitSelected != lease.Owner
                    || SeInteropFieldAliases.CommandMode(ref unit) != 1)
                {
                    return false;
                }
                selection = new UiSelectionSnapshot
                {
                    Lease = lease,
                    LeaseGeneration = lease.Generation,
                    UnitId = lease.UnitId,
                    GlobalId = lease.GlobalId,
                    Owner = lease.Owner,
                    Type = lease.Type,
                };
                return true;
            }
        }

        private bool IsLeasedUiMilitiaSnapshotCurrent(
            UiSelectionSnapshot expected)
        {
            UiSelectionSnapshot current;
            return expected != null
                && TryCaptureLeasedUiMilitia(out current)
                && UiSelectionSnapshotsMatch(expected, current);
        }

        private static bool UiSelectionSnapshotsMatch(
            UiSelectionSnapshot expected,
            UiSelectionSnapshot current)
        {
            return expected != null
                && current != null
                && ReferenceEquals(expected.Lease, current.Lease)
                && expected.LeaseGeneration == current.LeaseGeneration
                && expected.UnitId == current.UnitId
                && expected.GlobalId == current.GlobalId
                && expected.Owner == current.Owner
                && expected.Type == current.Type
                && IsMilitia(expected.Type);
        }

        private static bool UiSelectionSnapshotMatchesLease(
            UiSelectionSnapshot expected,
            NativeSelectionLease lease)
        {
            return expected != null
                && lease != null
                && ReferenceEquals(expected.Lease, lease)
                && expected.LeaseGeneration == lease.Generation
                && expected.UnitId == lease.UnitId
                && expected.GlobalId == lease.GlobalId
                && expected.Owner == lease.Owner
                && expected.Type == lease.Type
                && IsMilitia(expected.Type);
        }

        private void ApplyWorkerInformationUi(
            MainViewModel viewModel,
            UiSelectionSnapshot expected)
        {
            NativeSelectionLease lease;
            lock (_gate)
            {
                lease = _selectionLease;
                if (!UiSelectionSnapshotMatchesLease(expected, lease))
                {
                    return;
                }
            }

            string name = lease.WorkerInformationCacheValid
                ? lease.WorkerNameText ?? string.Empty
                : string.Empty;
            string typeText = lease.WorkerInformationCacheValid
                ? lease.WorkerTypeText ?? string.Empty
                : string.Empty;
            string comment = lease.WorkerInformationCacheValid
                ? lease.WorkerCommentText ?? string.Empty
                : string.Empty;
            string work = lease.WorkerInformationCacheValid
                ? lease.WorkerWorkText ?? string.Empty
                : string.Empty;
            if (!lease.WorkerInformationCacheValid)
            {
                string resolvedName;
                string resolvedType;
                string resolvedComment;
                if (TryResolveWorkerInformationFromUnit(
                        expected,
                        out resolvedName,
                        out resolvedType,
                        out resolvedComment))
                {
                    lock (_gate)
                    {
                        if (UiSelectionSnapshotMatchesLease(
                                expected,
                                _selectionLease))
                        {
                            lease.WorkerInformationCacheValid = true;
                            lease.WorkerNameText = resolvedName;
                            lease.WorkerTypeText = resolvedType;
                            lease.WorkerCommentText = resolvedComment;
                            lease.WorkerWorkText = string.Empty;
                            name = resolvedName;
                            typeText = resolvedType;
                            comment = resolvedComment;
                            work = string.Empty;
                        }
                    }
                }
            }
            viewModel.ChimpNameText = name;
            viewModel.ChimpTypeText = typeText;
            viewModel.ChimpCommentText = comment;
            viewModel.ChimpWorkText = work;
        }

        private bool TryResolveWorkerInformationFromUnit(
            UiSelectionSnapshot expected,
            out string name,
            out string typeText,
            out string comment)
        {
            name = string.Empty;
            typeText = string.Empty;
            comment = string.Empty;
            if (expected == null)
            {
                return false;
            }

            ushort packedName;
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                if (!UiSelectionSnapshotMatchesLease(expected, lease)
                    || units == null
                    || !units.TryGetUnitByIdEx(
                        expected.UnitId,
                        out var pointer))
                {
                    return false;
                }
                ref GameUnit unit = ref pointer.AsRef();
                // Identitaet, nicht Beschaeftigung: gelesen wird nur der
                // gepackte Name, und der haengt nicht am Arbeitsplatz. Sonst
                // verloere ein Jaeger mit abgebrannter Huette seinen Namen in
                // der Anzeige.
                if (unit.r_AliveState != AliveState.IsAlive
                    || !SelectionLeaseIdentityMatches(lease, ref unit)
                    || unit.r_UnitHover != 1
                    || unit.r_UnitSelected != lease.Owner
                    || SeInteropFieldAliases.CommandMode(ref unit) != 1)
                {
                    return false;
                }
                packedName = SeInteropFieldAliases.WorkerName(ref unit);
            }

            Translate translate = Translate.Instance;
            Dictionary<string, string> gameTexts = translate == null
                ? null
                : translate.GameTexts;
            if (gameTexts == null || gameTexts.Count == 0)
            {
                return false;
            }

            // The pinned native serializer uses signed byte loads here. Name
            // IDs outside the non-negative text-table range are rejected
            // instead of indexing Translate.GameTexts with an invented key.
            int nameIndex = unchecked((sbyte)(packedName & 0xFF));
            int surnameIndex = unchecked((sbyte)(packedName >> 8));
            if (nameIndex < 0
                || !TryGetLocalizedText(
                    gameTexts,
                    Enums.eTextSections.TEXT_PEASANT_NAMES,
                    nameIndex,
                    out name)
                || !TryGetLocalizedText(
                    gameTexts,
                    Enums.eTextSections.TEXT_CHIMP_NAMES,
                    (int)expected.Type,
                    out typeText)
                || !TrySelectLocalizedWorkerComment(
                    gameTexts,
                    expected.GlobalId,
                    out comment))
            {
                name = string.Empty;
                typeText = string.Empty;
                comment = string.Empty;
                return false;
            }
            if (surnameIndex > 0
                && TryGetLocalizedText(
                    gameTexts,
                    Enums.eTextSections.TEXT_PEASANT_SURNAMES,
                    surnameIndex,
                    out var surname))
            {
                name += " " + surname;
            }

            // Localization work can execute arbitrary dictionary access. Bind
            // its result only if the exact native singleton and lease identity
            // are still current after all lookups.
            if (!IsLeasedUiMilitiaSnapshotCurrent(expected))
            {
                name = string.Empty;
                typeText = string.Empty;
                comment = string.Empty;
                return false;
            }
            return true;
        }

        private static bool TryGetLocalizedText(
            Dictionary<string, string> gameTexts,
            Enums.eTextSections section,
            int zeroBasedIndex,
            out string value)
        {
            value = string.Empty;
            if (gameTexts == null || zeroBasedIndex < 0)
            {
                return false;
            }
            string key = section.ToString()
                + "_"
                + (zeroBasedIndex + 1).ToString(
                    "D3",
                    CultureInfo.InvariantCulture);
            return gameTexts.TryGetValue(key, out value)
                && !string.IsNullOrWhiteSpace(value);
        }

        private static bool TrySelectLocalizedWorkerComment(
            Dictionary<string, string> gameTexts,
            int globalId,
            out string comment)
        {
            comment = string.Empty;
            if (gameTexts == null || globalId <= 0)
            {
                return false;
            }
            var comments = new List<string>();
            // Native worker information treats comment ID zero as "no line".
            // Walk the same one-based IDs in a stable order and retain only
            // keys that actually exist in the active localization.
            for (int index = 1; index < 999; index++)
            {
                string candidate;
                if (TryGetLocalizedText(
                        gameTexts,
                        Enums.eTextSections.TEXT_CHIMP_COMMENT,
                        index,
                        out candidate))
                {
                    comments.Add(candidate);
                }
            }
            if (comments.Count == 0)
            {
                return false;
            }
            int selected = (int)((uint)globalId % (uint)comments.Count);
            comment = comments[selected];
            return true;
        }

        private void LogMilitiaUiOriginalFallbackTelemetry(
            UiSelectionSnapshot selection,
            string reason,
            Exception exception)
        {
            try
            {
                string unit = selection == null
                    ? "unknown"
                    : UnitName(selection.Type);
                string key = "ui_original_fallback." + unit + "." + reason;
                lock (_gate)
                {
                    if (!_evidenceLogged.Add(key))
                    {
                        return;
                    }
                }
                _warning(
                    "Worker militia UI returned to the original game route: unit="
                    + unit + " unit_id="
                    + (selection == null ? 0 : selection.UnitId).ToString(
                        CultureInfo.InvariantCulture)
                    + " global_id="
                    + (selection == null ? 0 : selection.GlobalId).ToString(
                        CultureInfo.InvariantCulture)
                    + " lease_generation="
                    + (selection == null ? 0L : selection.LeaseGeneration).ToString(
                        CultureInfo.InvariantCulture)
                    + " reason=" + reason
                    + (exception == null
                        ? string.Empty
                        : " exception=" + exception.GetType().Name + ": "
                            + exception.Message)
                    + ".");
            }
            catch
            {
                // A diagnostic sink must never prevent the Harmony prefix from
                // returning true and handing normalization back to the game.
            }
        }

        private void LogMilitiaUiThreadMismatchTelemetry(
            UiSelectionSnapshot selection,
            bool fromInitialOpening,
            int currentThreadId,
            int mainThreadId)
        {
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                if (!UiSelectionSnapshotMatchesLease(selection, lease)
                    || lease.UiThreadMismatchTelemetryLogged)
                {
                    return;
                }
                lease.UiThreadMismatchTelemetryLogged = true;
            }
            _warning(
                "Worker militia UI route telemetry: unit="
                + UnitName(selection.Type) + " unit_id="
                + selection.UnitId.ToString(CultureInfo.InvariantCulture)
                + " global_id="
                + selection.GlobalId.ToString(CultureInfo.InvariantCulture)
                + " route=" + (fromInitialOpening
                    ? "initial_opening"
                    : "selection_update")
                + " current_thread="
                + currentThreadId.ToString(CultureInfo.InvariantCulture)
                + " main_thread="
                + mainThreadId.ToString(CultureInfo.InvariantCulture)
                + " thread_match=false ui_mutation=blocked.");
        }

        private void LogMilitiaUiRouteTelemetry(
            UiSelectionSnapshot selection,
            bool fromInitialOpening,
            bool beforeMain,
            bool beforeTroops,
            bool beforeBuilding,
            bool beforeControlGroups,
            bool afterMain,
            bool afterTroops,
            bool afterBuilding,
            bool afterControlGroups,
            int currentThreadId,
            int mainThreadId)
        {
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                if (!UiSelectionSnapshotMatchesLease(selection, lease)
                    || lease.UiRouteTelemetryLogged)
                {
                    return;
                }
                lease.UiRouteTelemetryLogged = true;
            }
            EngineInterface.PlayState state = GameData.Instance == null
                ? null
                : GameData.Instance.lastGameState;
            int appMode = state == null ? -1 : state.app_mode;
            int appSubMode = state == null ? -1 : state.app_sub_mode;
            int inChimp = state == null ? -1 : state.in_chimp;
            int inChimpType = state == null ? -1 : state.in_chimp_type;
            bool inChimpMatches = state != null
                && inChimp == selection.UnitId
                && inChimpType == (int)selection.Type;
            _info(
                "Worker militia UI route telemetry: unit="
                + UnitName(selection.Type) + " unit_id="
                + selection.UnitId.ToString(CultureInfo.InvariantCulture)
                + " global_id="
                + selection.GlobalId.ToString(CultureInfo.InvariantCulture)
                + " route=" + (fromInitialOpening
                    ? "initial_opening"
                    : "selection_update")
                + " from_initial_opening="
                + TelemetryBoolean(fromInitialOpening)
                + " app_mode="
                + appMode.ToString(CultureInfo.InvariantCulture)
                + " app_sub_mode="
                + appSubMode.ToString(CultureInfo.InvariantCulture)
                + " in_chimp="
                + inChimp.ToString(CultureInfo.InvariantCulture)
                + " in_chimp_type="
                + inChimpType.ToString(CultureInfo.InvariantCulture)
                + " in_chimp_match="
                + TelemetryBoolean(inChimpMatches)
                + " current_thread="
                + currentThreadId.ToString(CultureInfo.InvariantCulture)
                + " main_thread="
                + mainThreadId.ToString(CultureInfo.InvariantCulture)
                + " thread_match="
                + TelemetryBoolean(
                    mainThreadId > 0 && currentThreadId == mainThreadId)
                + " before_main=" + TelemetryBoolean(beforeMain)
                + " before_troops=" + TelemetryBoolean(beforeTroops)
                + " before_building=" + TelemetryBoolean(beforeBuilding)
                + " before_control_groups="
                + TelemetryBoolean(beforeControlGroups)
                + " after_main=" + TelemetryBoolean(afterMain)
                + " after_troops=" + TelemetryBoolean(afterTroops)
                + " after_building=" + TelemetryBoolean(afterBuilding)
                + " after_control_groups="
                + TelemetryBoolean(afterControlGroups) + ".");
        }

        private void ScheduleMilitiaUiEvidence(
            MainViewModel viewModel,
            UiSelectionSnapshot selection,
            bool fromInitialOpening)
        {
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                string unit = selection == null
                    ? "unknown"
                    : UnitName(selection.Type);
                if (!IsOperationalLocked()
                    || viewModel == null
                    || !UiSelectionSnapshotMatchesLease(selection, lease)
                    || lease.TemporarilySuppressed
                    || _selectedWorkerId != selection.UnitId
                    || _pendingSelectionWorkerId != 0
                    || _nativeSelectionLifecycle
                        != NativeSelectionLifecycle.Confirmed
                    || Thread.CurrentThread.ManagedThreadId != _mainThreadId
                    || _evidenceLogged.Contains("ui_ready." + unit))
                {
                    return;
                }
                lease.UiEvidence = new PendingUiEvidence
                {
                    ViewModel = viewModel,
                    LeaseGeneration = lease.Generation,
                    UnitId = lease.UnitId,
                    GlobalId = lease.GlobalId,
                    Owner = lease.Owner,
                    Type = lease.Type,
                    Route = fromInitialOpening
                        ? "initial_opening"
                        : "selection_update",
                    DueTickGeneration = _uiEvidenceTickGeneration + 1,
                };
            }
        }

        private void VerifyPendingMilitiaUiEvidence(
            long currentTickGeneration)
        {
            NativeSelectionLease expectedLease;
            PendingUiEvidence pending;
            lock (_gate)
            {
                expectedLease = _selectionLease;
                pending = expectedLease == null
                    ? null
                    : expectedLease.UiEvidence;
                if (!IsOperationalLocked()
                    || pending == null
                    || currentTickGeneration < pending.DueTickGeneration)
                {
                    return;
                }
                // Consume this exact attempt before touching managed UI state.
                // A later direct selection may schedule a fresh lease-bound
                // attempt, but this frame can never be reported twice.
                expectedLease.UiEvidence = null;
                if (!PendingUiEvidenceMatchesLease(pending, expectedLease))
                {
                    return;
                }
            }

            int currentThreadId = Thread.CurrentThread.ManagedThreadId;
            if (_mainThreadId <= 0 || currentThreadId != _mainThreadId)
            {
                LogMilitiaUiEvidenceRejected(
                    pending,
                    "thread_mismatch",
                    new InvalidOperationException(
                        "Worker militia UI evidence reached a non-main thread"));
                return;
            }

            try
            {
                if (!ReferenceEquals(MainViewModel.Instance, pending.ViewModel))
                {
                    LogMilitiaUiEvidenceRejected(
                        pending,
                        "superseded_view_model",
                        null);
                    return;
                }

                int selectedMilitia;
                eChimps selectedType;
                if (!TryGetLeasedUiMilitia(
                        out selectedMilitia,
                        out selectedType)
                    || selectedMilitia != pending.UnitId
                    || selectedType != pending.Type)
                {
                    return;
                }
                string expectedName;
                string expectedTypeText;
                string expectedComment;
                bool informationCacheValid;
                lock (_gate)
                {
                    if (!ReferenceEquals(_selectionLease, expectedLease)
                        || !PendingUiEvidenceMatchesLease(
                            pending,
                            expectedLease))
                    {
                        return;
                    }
                    informationCacheValid =
                        expectedLease.WorkerInformationCacheValid;
                    expectedName = expectedLease.WorkerNameText
                        ?? string.Empty;
                    expectedTypeText = expectedLease.WorkerTypeText
                        ?? string.Empty;
                    expectedComment = expectedLease.WorkerCommentText
                        ?? string.Empty;
                }

                EngineInterface.PlayState state = GameData.Instance == null
                    ? null
                    : GameData.Instance.lastGameState;
                bool inChimpMatches = state != null
                    && state.in_chimp == pending.UnitId
                    && state.in_chimp_type == (int)pending.Type;
                bool building = pending.ViewModel.Show_HUD_Building;
                bool troops = pending.ViewModel.Show_HUD_Troops;
                bool controlGroups =
                    pending.ViewModel.Show_HUD_ControlGroups;
                bool panelVisible;
                bool imageBound;
                ReadMilitiaUiTree(
                    pending.ViewModel,
                    out panelVisible,
                    out imageBound);
                bool namePresent = !string.IsNullOrWhiteSpace(
                    pending.ViewModel.ChimpNameText);
                bool typePresent = !string.IsNullOrWhiteSpace(
                    pending.ViewModel.ChimpTypeText);
                bool commentPresent = !string.IsNullOrWhiteSpace(
                    pending.ViewModel.ChimpCommentText);
                bool informationBound = informationCacheValid
                    && string.Equals(
                        pending.ViewModel.ChimpNameText,
                        expectedName,
                        StringComparison.Ordinal)
                    && string.Equals(
                        pending.ViewModel.ChimpTypeText,
                        expectedTypeText,
                        StringComparison.Ordinal)
                    && string.Equals(
                        pending.ViewModel.ChimpCommentText,
                        expectedComment,
                        StringComparison.Ordinal);
                bool ready = informationBound
                    && building
                    && !troops
                    && !controlGroups
                    && panelVisible
                    && imageBound
                    && namePresent
                    && typePresent
                    && commentPresent;
                if (!ready)
                {
                    _warning(
                        "Worker militia stable UI evidence was incomplete: unit="
                        + UnitName(pending.Type) + " unit_id="
                        + pending.UnitId.ToString(CultureInfo.InvariantCulture)
                        + " global_id="
                        + pending.GlobalId.ToString(CultureInfo.InvariantCulture)
                        + " in_chimp_match="
                        + TelemetryBoolean(inChimpMatches)
                        + " info_source=unit_fields"
                        + " information_bound="
                        + TelemetryBoolean(informationBound)
                        + " building=" + TelemetryBoolean(building)
                        + " troops=" + TelemetryBoolean(troops)
                        + " control_groups="
                        + TelemetryBoolean(controlGroups)
                        + " panel_visible="
                        + TelemetryBoolean(panelVisible)
                        + " image_bound=" + TelemetryBoolean(imageBound)
                        + " name=" + TelemetryBoolean(namePresent)
                        + " type=" + TelemetryBoolean(typePresent)
                        + " comment=" + TelemetryBoolean(commentPresent)
                        + ".");
                    return;
                }

                // Re-read the exact native singleton after the reflected UI
                // checks. A simulation-thread deselection or slot reuse may
                // have happened while the main-thread tree was inspected.
                if (!TryGetLeasedUiMilitia(
                        out selectedMilitia,
                        out selectedType)
                    || selectedMilitia != pending.UnitId
                    || selectedType != pending.Type)
                {
                    return;
                }
                bool emit;
                string unit = UnitName(pending.Type);
                lock (_gate)
                {
                    emit = ReferenceEquals(_selectionLease, expectedLease)
                        && PendingUiEvidenceMatchesLease(
                            pending,
                            expectedLease)
                        && expectedLease.WorkerInformationCacheValid
                        && string.Equals(
                            expectedLease.WorkerNameText,
                            expectedName,
                            StringComparison.Ordinal)
                        && string.Equals(
                            expectedLease.WorkerTypeText,
                            expectedTypeText,
                            StringComparison.Ordinal)
                        && string.Equals(
                            expectedLease.WorkerCommentText,
                            expectedComment,
                            StringComparison.Ordinal)
                        && _evidenceLogged.Add("ui_ready." + unit);
                }
                if (emit)
                {
                    _info(RuntimeLogContract.WorkerMilitiaUiReadyEvidence(
                        unit,
                        pending.Route));
                }
            }
            catch (Exception exception)
            {
                // Observability must never become an availability dependency.
                // Reject this one evidence sample without touching selection,
                // UI state, commands, damage or the feature lifecycle.
                LogMilitiaUiEvidenceRejected(
                    pending,
                    "structural_readback_exception",
                    exception);
            }
        }

        private void LogMilitiaUiEvidenceRejected(
            PendingUiEvidence pending,
            string reason,
            Exception exception)
        {
            try
            {
                string unit = pending == null
                    ? "unknown"
                    : UnitName(pending.Type);
                string key = "ui_evidence_rejected." + unit + "." + reason;
                lock (_gate)
                {
                    if (!_evidenceLogged.Add(key))
                    {
                        return;
                    }
                }
                _warning(
                    "Worker militia UI evidence rejected nonfatally: unit="
                    + unit + " unit_id="
                    + (pending == null ? 0 : pending.UnitId).ToString(
                        CultureInfo.InvariantCulture)
                    + " global_id="
                    + (pending == null ? 0 : pending.GlobalId).ToString(
                        CultureInfo.InvariantCulture)
                    + " lease_generation="
                    + (pending == null ? 0L : pending.LeaseGeneration).ToString(
                        CultureInfo.InvariantCulture)
                    + " reason=" + reason
                    + (exception == null
                        ? string.Empty
                        : " exception=" + exception.GetType().Name + ": "
                            + exception.Message)
                    + "; feature_state=unchanged.");
            }
            catch
            {
                // Evidence is observability only. Even a failing warning sink
                // must not escape into the persistent main-thread Tick.
            }
        }

        private static bool PendingUiEvidenceMatchesLease(
            PendingUiEvidence pending,
            NativeSelectionLease lease)
        {
            return pending != null
                && lease != null
                && pending.LeaseGeneration == lease.Generation
                && pending.UnitId == lease.UnitId
                && pending.GlobalId == lease.GlobalId
                && pending.Owner == lease.Owner
                && pending.Type == lease.Type
                && IsMilitia(pending.Type);
        }

        private static void ReadMilitiaUiTree(
            MainViewModel viewModel,
            out bool panelVisible,
            out bool imageBound)
        {
            object hud = viewModel == null
                ? null
                : (object)viewModel.HUDBuildingPanel;
            if (hud == null)
            {
                throw new InvalidOperationException(
                    "Worker militia HUD_Buildings instance is unavailable");
            }
            Type hudType = hud.GetType();
            FieldInfo chimpPanelField = hudType.GetField(
                "RefChimpPanel",
                BindingFlags.Public
                | BindingFlags.Instance
                | BindingFlags.DeclaredOnly);
            if (chimpPanelField == null
                || !string.Equals(
                    chimpPanelField.FieldType.FullName,
                    "Noesis.Grid",
                    StringComparison.Ordinal))
            {
                throw new MissingFieldException(
                    "HUD_Buildings.RefChimpPanel is unavailable/nonexact");
            }
            object chimpPanel = chimpPanelField.GetValue(hud);
            if (chimpPanel == null
                || !string.Equals(
                    chimpPanel.GetType().FullName,
                    "Noesis.Grid",
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "HUD_Buildings.RefChimpPanel value is unavailable/nonexact");
            }
            PropertyInfo visibilityProperty = chimpPanel.GetType().GetProperty(
                "Visibility",
                BindingFlags.Public | BindingFlags.Instance);
            if (visibilityProperty == null
                || !visibilityProperty.CanRead
                || visibilityProperty.GetIndexParameters().Length != 0
                || !string.Equals(
                    visibilityProperty.PropertyType.FullName,
                    "Noesis.Visibility",
                    StringComparison.Ordinal))
            {
                throw new MissingMemberException(
                    "HUD_Buildings.RefChimpPanel.Visibility is unavailable/nonexact");
            }
            object visibility = visibilityProperty.GetValue(chimpPanel, null);
            panelVisible = visibility != null
                && string.Equals(
                    visibility.GetType().FullName,
                    "Noesis.Visibility",
                    StringComparison.Ordinal)
                && Convert.ToInt32(
                    visibility,
                    CultureInfo.InvariantCulture) == 2;

            MethodInfo findName = hudType.GetMethod(
                "FindName",
                BindingFlags.Public | BindingFlags.Instance,
                null,
                new[] { typeof(string) },
                null);
            if (findName == null)
            {
                throw new MissingMethodException(
                    "HUD_Buildings.FindName(string) is unavailable");
            }
            object sketch = findName.Invoke(
                hud,
                new object[] { "BuildingSketch" });
            if (sketch == null
                || !string.Equals(
                    sketch.GetType().FullName,
                    "Noesis.Image",
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "HUD_Buildings.BuildingSketch is unavailable/nonexact");
            }
            PropertyInfo sourceProperty = sketch.GetType().GetProperty(
                "Source",
                BindingFlags.Public | BindingFlags.Instance);
            PropertyInfo sketchImageProperty = typeof(MainViewModel).GetProperty(
                "SketchImage",
                BindingFlags.Public
                | BindingFlags.Instance
                | BindingFlags.DeclaredOnly);
            if (sourceProperty == null
                || !sourceProperty.CanRead
                || sourceProperty.GetIndexParameters().Length != 0
                || !string.Equals(
                    sourceProperty.PropertyType.FullName,
                    "Noesis.ImageSource",
                    StringComparison.Ordinal)
                || sketchImageProperty == null
                || !sketchImageProperty.CanRead
                || sketchImageProperty.GetIndexParameters().Length != 0
                || !string.Equals(
                    sketchImageProperty.PropertyType.FullName,
                    "Noesis.ImageSource",
                    StringComparison.Ordinal))
            {
                throw new MissingMemberException(
                    "Worker militia sketch image binding is unavailable/nonexact");
            }
            object source = sourceProperty.GetValue(sketch, null);
            object expectedSource = sketchImageProperty.GetValue(
                viewModel,
                null);
            imageBound = source != null
                && expectedSource != null
                && ReferenceEquals(source, expectedSource);
        }

        private bool TryArmNativeSelection(int unitId)
        {
            lock (_gate)
            {
                if (_nativeSelectionDisabledForProcess)
                {
                    return false;
                }
                if (_selectionLease != null
                    && _selectionLease.UnitId != unitId)
                {
                    if (_pendingSelectionWorkerId > 0)
                    {
                        RequestOutstandingSelectionCancellation(
                            "different worker selected while native selection was pending",
                            false,
                            false);
                        return false;
                    }
                    ReleaseNativeSelection("different worker selected");
                }
                GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                if (!units.TryGetUnitByIdEx(unitId, out var pointer))
                {
                    return false;
                }
                ref GameUnit unit = ref pointer.AsRef();
                int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
                if (unit.r_AliveState != AliveState.IsAlive
                    || !IsMilitia(unit.r_UnitChimp)
                    || unit.r_ControllableForPlayerId != localPlayer)
                {
                    return false;
                }
                if (_selectionLease != null)
                {
                    if (!SelectionLeaseMatches(_selectionLease, ref unit))
                    {
                        if (_pendingSelectionWorkerId > 0)
                        {
                            RequestOutstandingSelectionCancellation(
                                "unit slot identity changed",
                                true,
                                true);
                        }
                        else
                        {
                            ReleaseNativeSelection("unit slot identity changed");
                        }
                        return false;
                    }
                    if (_selectionLease.TemporarilySuppressed)
                    {
                        RestoreTemporarilySuppressedSelection();
                    }
                    string existingPatchReason;
                    if (!TryBeginCommandClassLease(
                            _selectionLease,
                            out existingPatchReason))
                    {
                        return false;
                    }
                    return SeInteropFieldAliases.SelectionBlocker(ref unit) == 0
                        && SeInteropFieldAliases.CommandMode(ref unit) == 1
                        && (unit.r_UnitSelected == 0
                            || unit.r_UnitSelected == localPlayer);
                }
                CommandState activeCommand;
                bool commandOwnsMode = _commands.TryGetValue(
                        unitId,
                        out activeCommand)
                    && activeCommand.OwnsCommandMode
                    && !activeCommand.Homeless
                    && activeCommand.Occupancy != null
                    && activeCommand.WorkerGlobalId
                        == unchecked((int)unit.r_GlobalId)
                    && activeCommand.WorkerOwner
                        == unit.r_ControllableForPlayerId
                    && activeCommand.WorkerType == unit.r_UnitChimp
                    && CommandMatchesLiveWorkerProvenance(
                        activeCommand,
                        unitId);
                OccupancyProvenance occupancy;
                if (commandOwnsMode)
                {
                    occupancy = CopyOccupancy(activeCommand.Occupancy);
                }
                else if (!TryCaptureWorkerOccupancy(
                        unitId,
                        unchecked((int)unit.r_GlobalId),
                        unit.r_ControllableForPlayerId,
                        unit.r_UnitChimp,
                        out occupancy))
                {
                    _warning(
                        "Worker militia refused native selection because the "
                        + "worker no longer owns an exact live workplace slot.");
                    return false;
                }
                int liveTribe = units.GetTribe(unitId);
                if (liveTribe != 0
                    && unit.r_UnitSelected == 0
                    && unitId == _lastConfirmedSelectionUnitId
                    && liveTribe == _lastConfirmedSelectionTribeId)
                {
                    // Our own singleton selection tribe survived the game's
                    // chore-0x0F deselection (no lease was around to dissolve
                    // it, e.g. after a map reload). Dissolve it now so the
                    // lease starts from the real pre-selection tribe.
                    TryDissolveStaleSelectionTribe(
                        unitId,
                        unit.r_ControllableForPlayerId,
                        0,
                        ref unit,
                        "direct click on a worker left in its stale selection tribe");
                    liveTribe = units.GetTribe(unitId);
                }
                if (liveTribe != 0)
                {
                    _warning(
                        "Worker militia refused native selection because the "
                        + "worker already belongs to tribe "
                        + liveTribe.ToString(CultureInfo.InvariantCulture)
                        + "; only a worker outside any tribe can be leased "
                        + "(a live tribe here means a foreign selection or "
                        + "group, not one of ours).");
                    return false;
                }
                int originalWorkLink = commandOwnsMode
                    ? activeCommand.OriginalWorkLink
                    : ReadExposedUnitInt(
                        unitId,
                        "r_LinkedProductionBuildingId");
                var originalPosition = units.GetCurrentLocalTilePosition(unitId);
                ushort expectedCommandMode = commandOwnsMode
                    ? (ushort)1
                    : (ushort)0;
                if (unit.r_UnitHover != 0
                    || SeInteropFieldAliases.SelectionBlocker(ref unit) != 0
                    || unit.N0000011E != 0
                    || SeInteropFieldAliases.SelectionRelevant(ref unit) != 0
                    || unit.r_AIState == 109
                    || unit.r_AIState == 110
                    || SeInteropFieldAliases.CommandMode(ref unit) != expectedCommandMode
                    || unit.r_UnitSelected != 0)
                {
                    _warning(
                        "Worker militia refused non-default native selection state: "
                        + "unit_id=" + unitId.ToString(CultureInfo.InvariantCulture)
                        + " selected_state=" + unit.r_UnitHover.ToString(
                            CultureInfo.InvariantCulture)
                        + " blocker=" + SeInteropFieldAliases.SelectionBlocker(ref unit).ToString(
                            CultureInfo.InvariantCulture)
                        + " auxiliary=" + unit.N0000011E.ToString(
                            CultureInfo.InvariantCulture)
                        + " selection_owner="
                        + unit.r_UnitSelected.ToString(
                            CultureInfo.InvariantCulture)
                        + " selection_relevant="
                        + SeInteropFieldAliases.SelectionRelevant(ref unit).ToString(
                            CultureInfo.InvariantCulture)
                        + " ai_state=" + unit.r_AIState.ToString(
                            CultureInfo.InvariantCulture)
                        + " command_mode=" + SeInteropFieldAliases.CommandMode(ref unit).ToString(
                            CultureInfo.InvariantCulture) + ".");
                    return false;
                }
                var lease = new NativeSelectionLease
                {
                    Generation = ++_selectionLeaseGeneration,
                    UnitId = unitId,
                    GlobalId = unchecked((int)unit.r_GlobalId),
                    Owner = unit.r_ControllableForPlayerId,
                    Type = unit.r_UnitChimp,
                    OriginalCommandModeValue = commandOwnsMode
                        ? activeCommand.OriginalCommandModeValue
                        : SeInteropFieldAliases.CommandMode(ref unit),
                    OriginalSelectionOwnerValue = unit.r_UnitSelected,
                    OriginalTribeId = commandOwnsMode
                        ? activeCommand.OriginalTribeId
                        : liveTribe,
                    OriginalWorkLink = originalWorkLink,
                    OriginalX = commandOwnsMode
                        ? activeCommand.OriginX
                        : originalPosition.X,
                    OriginalY = commandOwnsMode
                        ? activeCommand.OriginY
                        : originalPosition.Y,
                    // This method runs on Stronghold1Engine through
                    // getMouseStateForEngine. UI state is populated later by
                    // TroopsSelectedUiPrefix on the captured Unity thread.
                    WorkerInformationCacheValid = false,
                    WorkerNameText = string.Empty,
                    WorkerTypeText = string.Empty,
                    WorkerCommentText = string.Empty,
                    WorkerWorkText = string.Empty,
                    Occupancy = occupancy,
                };
                _selectionLease = lease;
                string patchReason;
                if (!TryBeginCommandClassLease(lease, out patchReason))
                {
                    if (ReferenceEquals(_selectionLease, lease)
                        && !lease.CommandClassApplied
                        && _commandClassLeaseGeneration == 0)
                    {
                        _selectionLease = null;
                    }
                    return false;
                }
                SeInteropFieldAliases.CommandMode(ref unit) = 1;
                if (SeInteropFieldAliases.CommandMode(ref unit) != 1 || unit.r_UnitSelected != 0)
                {
                    // Der eigene Schreibversuch hat nicht getragen. Das ist
                    // ein misslungener Anlauf, kein Vertragsbruch - und dies
                    // ist ein Try-Verfahren. Der Vorwert steht schon wieder;
                    // der Klick geht verloren, das Merkmal laeuft weiter.
                    SeInteropFieldAliases.CommandMode(ref unit) = expectedCommandMode;
                    EndCommandClassLease(
                        lease,
                        "command-mode readback failed while arming selection");
                    if (ReferenceEquals(_selectionLease, lease)
                        && !lease.CommandClassApplied
                        && _commandClassLeaseGeneration == 0)
                    {
                        _selectionLease = null;
                    }
                    if (_evidenceLogged.Add("arm_readback_failed"))
                    {
                        _warning(
                            "Worker militia could not make a worker selectable: "
                            + "the command-mode write did not hold (unit_id="
                            + unitId.ToString(CultureInfo.InvariantCulture)
                            + " command_mode="
                            + SeInteropFieldAliases.CommandMode(ref unit).ToString(CultureInfo.InvariantCulture)
                            + " selection_owner="
                            + unit.r_UnitSelected.ToString(
                                CultureInfo.InvariantCulture)
                            + "). The click is lost, the feature keeps running.");
                    }
                    return false;
                }
                return true;
            }
        }

        private void SuppressNativeSelectionForCycle(EditorDirector director)
        {
            lock (_gate)
            {
                NativeSelectionLease lease = _selectionLease;
                if (lease == null)
                {
                    return;
                }
                FilterWorkerFromNativeSelectionPacket(
                    director,
                    lease.UnitId);
                if (_pendingSelectionWorkerId > 0)
                {
                    RequestOutstandingSelectionCancellation(
                        "non-singleton selection input",
                        false,
                        false);
                    return;
                }
                // Any non-direct selection input ends the worker singleton
                // before DLL_TroopSelection sees it. This prevents Shift,
                // control groups and selection boxes from ever retaining a
                // militia worker in a multi-selection. An active mission keeps
                // command_mode=1 through ReleaseNativeSelection.
                _selectedWorkerId = 0;
                DeselectOwnedMilitia("non-singleton selection input");
                ReleaseNativeSelection("non-singleton selection input");
            }
        }

        private void RestoreTemporarilySuppressedSelection()
        {
            NativeSelectionLease lease = _selectionLease;
            if (lease == null || !lease.TemporarilySuppressed)
            {
                return;
            }
            if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    lease.UnitId,
                    out var pointer))
            {
                EndCommandClassLease(
                    lease,
                    "temporarily suppressed unit disappeared");
                _selectionLease = null;
                _selectedWorkerId = 0;
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (!SelectionLeaseMatches(lease, ref unit)
                || SeInteropFieldAliases.SelectionBlocker(ref unit) != 0
                || SeInteropFieldAliases.CommandMode(ref unit) != lease.OriginalCommandModeValue
                || unit.r_UnitSelected
                    != lease.OriginalSelectionOwnerValue)
            {
                EndCommandClassLease(
                    lease,
                    "temporary selection identity/provenance changed");
                _selectionLease = null;
                _selectedWorkerId = 0;
                _warning(
                    "Worker militia could not restore its temporary selection flag; "
                    + "foreign state was preserved.");
                return;
            }
            SeInteropFieldAliases.CommandMode(ref unit) = 1;
            unit.r_UnitSelected = checked((ushort)lease.Owner);
            if (SeInteropFieldAliases.CommandMode(ref unit) != 1
                || unit.r_UnitSelected != lease.Owner)
            {
                // Wie oben: der Schreibversuch trug nicht. Die Auswahl bleibt
                // unterdrueckt, der Spieler kann neu anwaehlen.
                if (_evidenceLogged.Add("restore_suppressed_readback_failed"))
                {
                    _warning(
                        "Worker militia could not restore a temporarily "
                        + "suppressed selection; it stays suppressed and the "
                        + "worker can simply be selected again.");
                }
                return;
            }
            lease.TemporarilySuppressed = false;
        }

        private void DeselectOwnedMilitia(string reason)
        {
            NativeSelectionLease lease = _selectionLease;
            if (lease == null
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    lease.UnitId,
                    out var pointer))
            {
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (!SelectionLeaseIdentityMatches(lease, ref unit))
            {
                return;
            }
            bool ownsCommittedSelection = unit.r_UnitHover != 0
                && unit.r_UnitSelected == lease.Owner;
            if (!ownsCommittedSelection)
            {
                // The game ended the selection itself (chore 0x0F): +0xAE is
                // already clear, but the singleton selection tribe the commit
                // created for this worker is still attached. Dissolve it so
                // the worker really is back in its pre-selection state.
                TryDissolveStaleSelectionTribe(
                    lease.UnitId,
                    lease.Owner,
                    lease.OriginalTribeId,
                    ref unit,
                    reason);
                return;
            }
            ClearPinnedNativeSelectionUnit(
                lease.UnitId,
                lease.Owner,
                reason);
            if (unit.r_UnitHover != 0
                || unit.r_UnitSelected != 0)
            {
                if (_evidenceLogged.Add("deselect_readback_failed"))
                {
                    _warning(
                        "Worker militia deselection did not read back clean "
                        + "(selected="
                        + unit.r_UnitHover.ToString(CultureInfo.InvariantCulture)
                        + " owner="
                        + unit.r_UnitSelected.ToString(CultureInfo.InvariantCulture)
                        + "); the engine keeps whatever it holds and the "
                        + "feature keeps running.");
                }
                return;
            }
            int workLink = ReadExposedUnitInt(
                lease.UnitId,
                "r_LinkedProductionBuildingId");
            int tribeId = GameUnitManagerAPI.Instance.GetTribe(lease.UnitId);
            if (workLink != lease.OriginalWorkLink
                || tribeId != lease.OriginalTribeId)
            {
                // Der Arbeitsplatz kann waehrend der Auswahl abgebrannt sein.
                // Das ist ein Spielereignis; gemeldet, nicht bestraft.
                if (_evidenceLogged.Add("deselect_provenance_changed"))
                {
                    _warning(
                        "Worker militia deselection found a changed "
                        + "work/tribe provenance (work_link=" + workLink
                            .ToString(CultureInfo.InvariantCulture)
                        + " expected=" + lease.OriginalWorkLink
                            .ToString(CultureInfo.InvariantCulture)
                        + " tribe=" + tribeId
                            .ToString(CultureInfo.InvariantCulture)
                        + " expected=" + lease.OriginalTribeId
                            .ToString(CultureInfo.InvariantCulture)
                        + "). Nothing was restored through it.");
                }
                return;
            }
            _info(
                "Worker militia cleared its native singleton selection during "
                + reason + ".");
        }

        /// <summary>
        /// Refuses one selection clear without stopping the feature.
        /// </summary>
        /// <remarks>
        /// Every refusal below means "do not touch this unit", and declining
        /// achieves exactly that. Until 2026-08-27 they threw, on a path the
        /// mouse postfix, the run postfix and the R3 events all reach, where a
        /// throw becomes a deferred failure and the host rolls the whole
        /// feature back. Two of them are outright ordinary: a unit that died
        /// before its deselection, and a human player who is not in slot one -
        /// the pinned clear at RVA 0x199300 was only ever measured for slot
        /// one, so anything else simply is not this shortcut's business.
        /// </remarks>
        private void RefuseNativeSelectionClear(string key, string message)
        {
            if (_evidenceLogged.Add("clear_refused." + key))
            {
                _warning(
                    "Worker militia did not clear a native selection: "
                    + message + ". Nothing was written; the feature keeps "
                    + "running.");
            }
        }

        private void ClearPinnedNativeSelectionUnit(
            int unitId,
            int selectionPlayer,
            string reason)
        {
            if (_nativeUnitSelectionMarkerClear == null
                || _nativePlayerSelectionClear == null
                || _nativeModuleBase == IntPtr.Zero)
            {
                RefuseNativeSelectionClear(
                    "unavailable",
                    "the pinned per-unit clear is unavailable");
                return;
            }
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            if (localPlayer < 1
                || localPlayer > 8
                || selectionPlayer != localPlayer)
            {
                RefuseNativeSelectionClear(
                    "foreign_player",
                    "the selection owner is not the valid local player "
                    + "(local_player="
                    + localPlayer.ToString(CultureInfo.InvariantCulture)
                    + " selection_player="
                    + selectionPlayer.ToString(CultureInfo.InvariantCulture)
                    + ")");
                return;
            }
            if (unitId <= 0
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                RefuseNativeSelectionClear(
                    "unit_gone",
                    "the unit is gone (unit_id="
                    + unitId.ToString(CultureInfo.InvariantCulture)
                    + ", during " + reason + ")");
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            int selectionOwnerBefore = unit.r_UnitSelected;
            bool markerWasSet = unit.r_UnitHover != 0;
            if (selectionOwnerBefore != 0
                && selectionOwnerBefore != selectionPlayer)
            {
                RefuseNativeSelectionClear(
                    "foreign_owner",
                    "the selection belongs to another player (owner="
                    + selectionOwnerBefore.ToString(CultureInfo.InvariantCulture)
                    + ")");
                return;
            }
            int hoveredBefore = GetPinnedNativeHoveredCount();
            int selectedBefore = GetPinnedNativeSelectedCount();
            if (hoveredBefore < 0 || selectedBefore < 0)
            {
                RefuseNativeSelectionClear(
                    "unreadable_counters",
                    "the pinned manager counters are not readable");
                return;
            }
            if ((markerWasSet && hoveredBefore <= 0)
                || (selectionOwnerBefore != 0 && selectedBefore <= 0))
            {
                RefuseNativeSelectionClear(
                    "inconsistent_counters",
                    "the pinned manager counters contradict the unit state "
                    + "(hovered=" + hoveredBefore.ToString(
                        CultureInfo.InvariantCulture)
                    + " selected=" + selectedBefore.ToString(
                        CultureInfo.InvariantCulture)
                    + " marker=" + TelemetryBoolean(markerWasSet)
                    + " owner=" + selectionOwnerBefore.ToString(
                        CultureInfo.InvariantCulture) + ")");
                return;
            }
            IntPtr manager = new IntPtr(
                _nativeModuleBase.ToInt64() + NativeUnitManagerRva);
            // This is the exact native order used for one committed unit:
            // 0x185960 clears +0x30 and decrements manager+0x20; only then
            // 0x199300(manager, owner, unitId, 0) removes its selection tribe,
            // clears +0xAE and decrements the owner's selected counter. The
            // latter is deliberately skipped for an uncommitted owner==0
            // candidate because it would otherwise remove a pre-existing
            // tribe even though no selection counter is owned.
            _nativeUnitSelectionMarkerClear(manager, unitId);
            if (selectionOwnerBefore != 0)
            {
                _nativePlayerSelectionClear(
                    manager,
                    selectionPlayer,
                    unitId,
                    0);
            }
            int expectedHovered = hoveredBefore - (markerWasSet ? 1 : 0);
            int expectedSelected = selectedBefore
                - (selectionOwnerBefore != 0 ? 1 : 0);
            if (unit.r_UnitHover != 0
                || unit.r_UnitSelected != 0
                || GetPinnedNativeHoveredCount() != expectedHovered
                || GetPinnedNativeSelectedCount() != expectedSelected)
            {
                // The clear itself already ran. Stopping the feature does not
                // undo it and cannot repair anything; it only guarantees that
                // nothing else works either. Reported with every number, so a
                // real model error is decidable from one log instead of one
                // crash.
                _warning(
                    "Worker militia native selection clear did not read back as "
                    + "expected during " + reason + ": selected="
                    + unit.r_UnitHover.ToString(CultureInfo.InvariantCulture)
                    + " owner="
                    + unit.r_UnitSelected.ToString(CultureInfo.InvariantCulture)
                    + " hovered="
                    + GetPinnedNativeHoveredCount().ToString(
                        CultureInfo.InvariantCulture)
                    + " expected_hovered="
                    + expectedHovered.ToString(CultureInfo.InvariantCulture)
                    + " selected_count="
                    + GetPinnedNativeSelectedCount().ToString(
                        CultureInfo.InvariantCulture)
                    + " expected_selected_count="
                    + expectedSelected.ToString(CultureInfo.InvariantCulture)
                    + ".");
            }
        }

        private void ReleaseNativeSelection(
            string reason,
            bool retainActiveCommandMode = true)
        {
            if (_pendingSelectionWorkerId > 0 && _selectionLease != null)
            {
                RequestOutstandingSelectionCancellation(
                    reason,
                    false,
                    false);
                return;
            }
            NativeSelectionLease lease = _selectionLease;
            bool leaseMatchesLiveUnit = false;
            if (lease != null
                && GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    lease.UnitId,
                    out var leasedPointer))
            {
                ref GameUnit leasedUnit = ref leasedPointer.AsRef();
                leaseMatchesLiveUnit = SelectionLeaseIdentityMatches(
                    lease,
                    ref leasedUnit);
            }
            if (leaseMatchesLiveUnit)
            {
                FilterWorkerFromNativeSelectionPacket(
                    EditorDirector.instance,
                    lease.UnitId);
                DeselectOwnedMilitia(reason);
            }
            RightClickGesture cancelledRightClick = _pendingRightClickGesture;
            bool keepRightClickGesture = false;
            if (cancelledRightClick != null)
            {
                InputPacket cancelledPacket = cancelledRightClick.Packet;
                bool gestureWorkerIntact = cancelledPacket != null
                    && RightClickGestureWorkerStillMatches(cancelledPacket);
                bool firstLoss = false;
                if (cancelledRightClick.SelectionLostAfterCapture)
                {
                    // CompleteNativeRun calls this release on every native run
                    // while nothing is selected; with no lease there is nothing
                    // to release, and the kept gesture must outlive these idle
                    // calls until its mouse-up, promotion or deadline. A new
                    // lease for another worker ends it.
                    keepRightClickGesture = lease == null && gestureWorkerIntact;
                }
                else
                {
                    // The engine itself ended the selection between the
                    // captured right mouse-down and the mouse-up (observed
                    // after every right-click order). The captured packet still
                    // names the exact worker; keep the gesture so the mouse-up
                    // can complete it against that identity and the post-run
                    // promotion still reaches the mission path. Any other
                    // release reason (different worker clicked, identity
                    // changed, rollback) discards the gesture as before.
                    keepRightClickGesture = string.Equals(
                            reason,
                            NativeDeselectionReleaseReason,
                            StringComparison.Ordinal)
                        && lease != null
                        && cancelledPacket != null
                        && cancelledPacket.SelectedWorkerId == lease.UnitId
                        && cancelledPacket.SelectedWorkerGlobalId == lease.GlobalId
                        && cancelledPacket.SelectedWorkerOwner == lease.Owner
                        && cancelledPacket.SelectedWorkerType == lease.Type
                        && gestureWorkerIntact;
                    firstLoss = keepRightClickGesture;
                    if (firstLoss)
                    {
                        cancelledRightClick.SelectionLostAfterCapture = true;
                    }
                }
                if (firstLoss || !keepRightClickGesture)
                {
                    LogRightClickGesture(
                        "promotion",
                        cancelledRightClick.Generation,
                        firstLoss ? "deferred" : "rejected",
                        firstLoss
                            ? "native_selection_released_gesture_kept"
                            : "native_selection_released",
                        cancelledPacket == null
                            ? 0
                            : cancelledPacket.SelectedWorkerId,
                        cancelledRightClick.Released
                            ? cancelledRightClick.NativeMouseStateAtUp
                            : cancelledRightClick.NativeMouseStateAtDown,
                        false,
                        false,
                        cancelledRightClick.HoveredUnitIdAtDown,
                        cancelledPacket != null
                            && cancelledPacket.HasGroundDestination,
                        cancelledPacket == null
                            ? 0
                            : cancelledPacket.GroundDestinationX,
                        cancelledPacket == null
                            ? 0
                            : cancelledPacket.GroundDestinationY);
                }
            }
            EndCommandClassLease(lease, reason);
            _selectionLease = null;
            _pendingSelectionWorkerId = 0;
            _nativeSelectionPacketInFlight = false;
            _directClickGestureUnitId = 0;
            _confirmedSelectionGestureNoOp = false;
            _directSelectionMouseUpAccepted = false;
            _pendingRightClickGesture = keepRightClickGesture
                ? cancelledRightClick
                : null;
            _pendingSelectionCancellationRequested = false;
            _pendingSelectionIdentityInvalidated = false;
            _pendingSelectionCancellationReason = null;
            _directSelectionDeadlineTick = 0;
            _nativeSelectionLifecycle = _nativeSelectionDisabledForProcess
                ? NativeSelectionLifecycle.Quarantined
                : NativeSelectionLifecycle.Idle;
            if (lease == null)
            {
                return;
            }
            if (!GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    lease.UnitId,
                    out var pointer))
            {
                return;
            }
            ref GameUnit unit = ref pointer.AsRef();
            if (!leaseMatchesLiveUnit
                || !SelectionLeaseIdentityMatches(lease, ref unit))
            {
                _warning(
                    "Worker militia selection slot changed identity during " + reason
                    + "; no native field was restored.");
                return;
            }
            ushort ownedCommandModeValue = lease.TemporarilySuppressed
                ? lease.OriginalCommandModeValue
                : (ushort)1;
            ushort ownedSelectionOwnerValue = lease.TemporarilySuppressed
                ? lease.OriginalSelectionOwnerValue
                : checked((ushort)lease.Owner);
            CommandState activeCommand = null;
            bool retainCommandMode = retainActiveCommandMode
                && _commands.TryGetValue(
                    lease.UnitId,
                    out activeCommand)
                && activeCommand.OwnsCommandMode
                && activeCommand.WorkerGlobalId == lease.GlobalId
                && activeCommand.WorkerOwner == lease.Owner
                && activeCommand.WorkerType == lease.Type;
            if (retainCommandMode
                && lease.TemporarilySuppressed
                && SeInteropFieldAliases.CommandMode(ref unit) == lease.OriginalCommandModeValue)
            {
                SeInteropFieldAliases.CommandMode(ref unit) = 1;
            }
            bool restoredCommandMode = retainCommandMode
                ? SeInteropFieldAliases.CommandMode(ref unit) == 1
                : SeInteropFieldAliases.CommandMode(ref unit) == lease.OriginalCommandModeValue;
            if (!retainCommandMode
                && !restoredCommandMode
                && SeInteropFieldAliases.CommandMode(ref unit) == ownedCommandModeValue)
            {
                SeInteropFieldAliases.CommandMode(ref unit) = lease.OriginalCommandModeValue;
                restoredCommandMode = SeInteropFieldAliases.CommandMode(ref unit)
                    == lease.OriginalCommandModeValue;
            }
            bool restoredSelectionOwner = unit.r_UnitSelected
                == lease.OriginalSelectionOwnerValue;
            if (!restoredSelectionOwner
                && unit.r_UnitSelected == ownedSelectionOwnerValue)
            {
                unit.r_UnitSelected = lease.OriginalSelectionOwnerValue;
                restoredSelectionOwner = unit.r_UnitSelected
                    == lease.OriginalSelectionOwnerValue;
            }
            if (!restoredCommandMode || !restoredSelectionOwner)
            {
                if (retainCommandMode && !restoredCommandMode)
                {
                    activeCommand.OwnsCommandMode = false;
                }
                _warning(
                    "Worker militia lost ownership of native singleton state during "
                    + reason + "; foreign command-selection value was preserved.");
                return;
            }
            if (retainCommandMode)
            {
                _info(
                    "Worker militia detached native selection during " + reason
                    + " while its active mission retained command_mode=1.");
                return;
            }
            string unitName = UnitName(lease.Type);
            if (_evidenceLogged.Add("native_state_restored." + unitName))
            {
                _info(RuntimeLogContract.WorkerMilitiaNativeStateRestoredEvidence(
                    unitName));
            }
        }

        /// <summary>
        /// Identitaet UND Beschaeftigung: derselbe Arbeiter, noch an demselben
        /// Arbeitsplatz. Fuer alles gedacht, was den Arbeitsplatz wirklich
        /// braucht - Speichern, Wiederherstellen, Oberflaeche.
        /// </summary>
        /// <remarks>
        /// NICHT als Identitaetspruefung verwenden. TryCaptureWorkerOccupancy
        /// scheitert, sobald das Gebaeude nicht mehr lebt; eine abgebrannte
        /// Jagdhuette liest sich hier also wie ein Identitaetswechsel. An
        /// mehreren Stellen fuehrte das bis zum 29.08.2026 zu
        /// _nativeSelectionDisabledForProcess - eine brennende Huette hat die
        /// Miliz fuer die restliche Partie abgeschaltet. Genau davor soll der
        /// Mod schuetzen: der Arbeiter verlaesst seine Arbeit, um zu kaempfen.
        /// Wer nur wissen will, ob es noch derselbe Arbeiter ist, nimmt
        /// SelectionLeaseIdentityMatches.
        /// </remarks>
        private static bool SelectionLeaseMatches(
            NativeSelectionLease lease,
            ref GameUnit unit)
        {
            return SelectionLeaseIdentityMatches(lease, ref unit)
                && WorkerOccupancyMatches(
                    lease.UnitId,
                    lease.GlobalId,
                    lease.Owner,
                    lease.Type,
                    lease.Occupancy);
        }

        private static bool SelectionLeaseIdentityMatches(
            NativeSelectionLease lease,
            ref GameUnit unit)
        {
            return lease != null
                && unit.r_AliveState == AliveState.IsAlive
                && unchecked((int)unit.r_GlobalId) == lease.GlobalId
                && unit.r_UnitChimp == lease.Type
                && unit.r_ControllableForPlayerId == lease.Owner;
        }

        private static IntPtr FindNativeModuleBase()
        {
            using (Process process = Process.GetCurrentProcess())
            {
                foreach (ProcessModule module in process.Modules)
                {
                    if (string.Equals(
                            module.ModuleName,
                            "CrusaderDE.dll",
                            StringComparison.OrdinalIgnoreCase))
                    {
                        return module.BaseAddress;
                    }
                }
            }
            return IntPtr.Zero;
        }

        private void EnqueueInput(InputPacket packet)
        {
            lock (_gate)
            {
                if (!IsOperationalLocked())
                {
                    return;
                }
                if (_inputPackets.Count >= MaxInputPackets)
                {
                    _inputPackets.Dequeue();
                    _warning("Worker militia native input queue overflowed; oldest packet dropped.");
                }
                _inputPackets.Enqueue(packet);
            }
        }

        private static bool IsLocalMilitia(int unitId)
        {
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            return unitId > 0
                && units != null
                && players != null
                && units.IsValid(unitId)
                && IsMilitia(units.GetType(unitId))
                && units.GetOwner(unitId) == players.GetLocalPlayerId();
        }

        /// <summary>
        /// Marks a pinned manager counter as unreadable. Callers must treat a
        /// negative count as "do not act", never as a number.
        /// </summary>
        /// <remarks>
        /// These two counters used to throw on an implausible value and on a
        /// disagreement with the Extender. Both are worth knowing and neither
        /// is worth the feature: they are read from the mouse postfix and the
        /// run postfix, where a throw becomes a deferred failure and the host
        /// rolls everything back. A disagreement in particular can be a single
        /// frame in which the engine and the Extender are one step apart.
        /// </remarks>
        private const int UnreadableNativeCount = -1;

        private int ReportUnreadableNativeCount(string key, string message)
        {
            if (_evidenceLogged.Add("native_count." + key))
            {
                _warning(
                    "Worker militia could not trust a pinned manager counter: "
                    + message + ". Every operation that needs it declines "
                    + "instead of acting.");
            }
            return UnreadableNativeCount;
        }

        private int GetPinnedNativeSelectedCount()
        {
            if (_nativeModuleBase == IntPtr.Zero)
            {
                return ReportUnreadableNativeCount(
                    "base",
                    "the pinned unit-manager base is unavailable");
            }
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            if (localPlayer < 1 || localPlayer > 8)
            {
                return ReportUnreadableNativeCount(
                    "local_player",
                    "the local player id is outside slots 1..8");
            }
            int selectedCount = Marshal.ReadInt32(new IntPtr(
                _nativeModuleBase.ToInt64()
                + NativeUnitManagerRva
                + SelectedCountOffsetForPlayer(localPlayer)));
            if (selectedCount < 0 || selectedCount > MaxNativeSelectedUnits)
            {
                return ReportUnreadableNativeCount(
                    "selected_bounds",
                    "the selected count is outside safe bounds ("
                    + selectedCount.ToString(CultureInfo.InvariantCulture)
                    + ")");
            }
            // Do not compare against GamePlayerManagerAPI.GetSelectedChimpsCount:
            // SHCDESE 1.39 reads GameUnitManager.r_SelectedChimpsCount at the
            // fixed +0x28 field, which is player slot 1. The native counter
            // above is manager+0x24+(localPlayer*4), the same generic indexing
            // used by commit RVA 0x190655 and clear RVA 0x1993A6, and is the
            // sole count authority for local slots 1..8.
            return selectedCount;
        }

        private static int SelectedCountOffsetForPlayer(int playerId)
        {
            // RVA 0x199300 indexes the selected counters as
            // manager+0x24+(player*4). The reflected slot-one field at +0x28
            // remains the layout pin; this formula extends the same native
            // array to every valid single-player slot.
            return NativeSelectedCountBaseOffset + (playerId * sizeof(int));
        }

        private int GetPinnedNativeHoveredCount()
        {
            if (_nativeModuleBase == IntPtr.Zero)
            {
                return ReportUnreadableNativeCount(
                    "base",
                    "the pinned unit-manager base is unavailable");
            }
            int hoveredCount = Marshal.ReadInt32(new IntPtr(
                _nativeModuleBase.ToInt64()
                + NativeUnitManagerRva
                + NativeHoveredCountOffset));
            if (hoveredCount < 0 || hoveredCount > MaxNativeSelectedUnits)
            {
                return ReportUnreadableNativeCount(
                    "hovered_bounds",
                    "the hovered count is outside safe bounds ("
                    + hoveredCount.ToString(CultureInfo.InvariantCulture)
                    + ")");
            }
            return hoveredCount;
        }

        private int[] GetPinnedNativeSelectedIds()
        {
            int selectedCount = GetPinnedNativeSelectedCount();
            if (selectedCount <= 0)
            {
                // Includes the unreadable case: an empty list is the safe
                // answer, and every caller already treats it as "nothing of
                // ours is selected".
                return Array.Empty<int>();
            }
            int[] selectedPairs;
            try
            {
                selectedPairs = _engineSelectedChimpsField == null
                    ? null
                    : _engineSelectedChimpsField.GetValue(null) as int[];
            }
            catch (Exception exception)
            {
                if (_evidenceLogged.Add("selected_pair_buffer_unreadable"))
                {
                    _warning(
                        "Worker militia could not read the exact native selected "
                        + "unit/type pair buffer: " + exception.GetType().Name
                        + ". This frame is treated as no selection of ours.");
                }
                return Array.Empty<int>();
            }
            if (selectedPairs == null
                || !ReferenceEquals(
                    selectedPairs,
                    _engineSelectedChimpsBuffer)
                || selectedPairs.Length != NativeSelectedPairBufferLength
                || selectedPairs.Length < selectedCount * 2)
            {
                if (_evidenceLogged.Add("selected_ids_disagree"))
                {
                    _warning(
                        "Worker militia saw an undersized native selected-pair "
                        + "buffer next to the slot-specific counter (buffer="
                        + (selectedPairs == null
                            ? "null"
                            : selectedPairs.Length.ToString(
                                CultureInfo.InvariantCulture))
                        + " required="
                        + (selectedCount * 2).ToString(
                            CultureInfo.InvariantCulture)
                        + " selected="
                        + selectedCount.ToString(CultureInfo.InvariantCulture)
                        + "). This frame is treated as no selection of ours.");
                }
                return Array.Empty<int>();
            }
            int localPlayer = GamePlayerManagerAPI.Instance.GetLocalPlayerId();
            var selectedIds = new int[selectedCount];
            var unique = new HashSet<int>();
            for (int index = 0; index < selectedCount; index++)
            {
                int unitId = selectedPairs[index * 2];
                int nativeType = selectedPairs[index * 2 + 1];
                if (unitId <= 0
                    || nativeType < 0
                    || nativeType >= ValidTargetCount
                    || !unique.Add(unitId)
                    || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                        unitId,
                        out var pointer))
                {
                    // The Extender hands out a snapshot of the selection. A
                    // unit that died in the same frame is an ordinary combat
                    // event, not a broken contract - and this list is read from
                    // the mouse postfix, where a throw stops the militia for
                    // the whole session. The frame is dropped instead.
                    if (_evidenceLogged.Add("selected_ids_invalid"))
                    {
                        _warning(
                            "Worker militia saw an invalid or duplicate id in "
                            + "the Extender selection list (unit_id="
                            + unitId.ToString(CultureInfo.InvariantCulture)
                            + "). This frame is treated as no selection of "
                            + "ours.");
                    }
                    return Array.Empty<int>();
                }
                ref GameUnit unit = ref pointer.AsRef();
                if (unit.r_AliveState != AliveState.IsAlive
                    || unit.r_UnitSelected != localPlayer
                    || (int)unit.r_UnitChimp != nativeType)
                {
                    if (_evidenceLogged.Add("selected_ids_owner_mismatch"))
                    {
                        _warning(
                            "Worker militia saw a selected unit that is dead or "
                            + "owned by someone else (unit_id="
                            + unitId.ToString(CultureInfo.InvariantCulture)
                            + " alive="
                            + unit.r_AliveState.ToString()
                        + " selection_owner="
                        + unit.r_UnitSelected.ToString(
                            CultureInfo.InvariantCulture)
                        + " pair_type="
                        + nativeType.ToString(CultureInfo.InvariantCulture)
                        + " live_type="
                        + ((int)unit.r_UnitChimp).ToString(
                            CultureInfo.InvariantCulture)
                            + " local_player="
                            + localPlayer.ToString(CultureInfo.InvariantCulture)
                            + "). This frame is treated as no selection of "
                            + "ours.");
                    }
                    return Array.Empty<int>();
                }
                selectedIds[index] = unitId;
            }
            return selectedIds;
        }

        private int TryGetNativeSelectedMilitia()
        {
            int[] selected = GetPinnedNativeSelectedIds();
            int selectedMilitia = selected != null
                && selected.Length == 1
                && IsLocalMilitia(selected[0])
                    ? selected[0]
                    : 0;
            if (selectedMilitia <= 0)
            {
                return 0;
            }
            lock (_gate)
            {
                return _nativeSelectionLifecycle
                            == NativeSelectionLifecycle.Confirmed
                        && _pendingSelectionWorkerId == 0
                        && _selectedWorkerId == selectedMilitia
                        && _selectionLease != null
                        && _selectionLease.UnitId == selectedMilitia
                    ? selectedMilitia
                    : 0;
            }
        }

        private bool IsNativeSingletonSelection(int unitId)
        {
            return unitId > 0 && TryGetNativeSelectedMilitia() == unitId;
        }

        // Reine Unsinnsgrenze, keine Balanceaussage. Die Beziehungen unten
        // (Angriff/Wache < Verfolgung) waren bisher die einzige Pruefung, und
        // ein Vertippen im Profil - 560 statt 56 - haette jeden Arbeiter der
        // Karte in jeden Kampf geschickt. HunterRangeCalibrated=true belegt
        // derzeit die native Bogenschuetzenmetrik und Reichweite 54; es belegt
        // weder die autonome Zielerfassung noch den gesamten Jaegerkampfpfad.
        // Diese separate Obergrenze bleibt deshalb weiterhin notwendig.
        private const int MaxPolicyRadiusTiles = 64;

        private static bool WorkerMilitiaPolicyIsSafe()
        {
            return GeneratedWorkerMilitiaContract.HunterPursuitRadius
                    <= MaxPolicyRadiusTiles
                && GeneratedWorkerMilitiaContract.WoodcutterPursuitRadius
                    <= MaxPolicyRadiusTiles
                && GeneratedWorkerMilitiaContract.HunterGuardRadius
                    <= MaxPolicyRadiusTiles
                && GeneratedWorkerMilitiaContract.WoodcutterGuardRadius
                    <= MaxPolicyRadiusTiles
                && GeneratedWorkerMilitiaContract.HunterAttackRange
                    <= MaxPolicyRadiusTiles
                && GeneratedWorkerMilitiaContract.WoodcutterAttackRange
                    <= MaxPolicyRadiusTiles
                && GeneratedWorkerMilitiaContract.DamageDivisor >= 2
                && GeneratedWorkerMilitiaContract.DamageDivisor <= 16
                && (GeneratedWorkerMilitiaContract.HunterRangeCalibrated
                    ? !string.IsNullOrWhiteSpace(
                        GeneratedWorkerMilitiaContract.HunterRangeEvidence)
                        && !string.Equals(
                            GeneratedWorkerMilitiaContract.HunterRangeEvidence,
                            "none",
                            StringComparison.Ordinal)
                    : string.Equals(
                        GeneratedWorkerMilitiaContract.HunterRangeEvidence,
                        "none",
                        StringComparison.Ordinal))
                && (GeneratedWorkerMilitiaContract.WorkerAnimationCalibrated
                    ? !string.IsNullOrWhiteSpace(
                        GeneratedWorkerMilitiaContract.WorkerAnimationEvidence)
                        && !string.Equals(
                            GeneratedWorkerMilitiaContract.WorkerAnimationEvidence,
                            "none",
                            StringComparison.Ordinal)
                    : string.Equals(
                        GeneratedWorkerMilitiaContract.WorkerAnimationEvidence,
                        "none",
                        StringComparison.Ordinal))
                && string.Equals(
                    GeneratedWorkerMilitiaContract.NativeRangeMetric,
                    "euclidean_squared_inclusive",
                    StringComparison.Ordinal)
                && GeneratedWorkerMilitiaContract.WorldTilesPerLocalTile
                    == WorldTilesPerLocalTile
                && GeneratedWorkerMilitiaContract.VanillaArcherAttackRange == 54
                && GeneratedWorkerMilitiaContract.HunterGuardRadius
                    > GeneratedWorkerMilitiaContract.WoodcutterGuardRadius
                && GeneratedWorkerMilitiaContract.WoodcutterGuardRadius >= 2
                && GeneratedWorkerMilitiaContract.HunterAttackRange
                    == GeneratedWorkerMilitiaContract.HunterGuardRadius
                && GeneratedWorkerMilitiaContract.HunterAttackRange
                    == GeneratedWorkerMilitiaContract.VanillaArcherAttackRange
                && GeneratedWorkerMilitiaContract.WoodcutterAttackRange >= 1
                && GeneratedWorkerMilitiaContract.HunterPursuitRadius
                    == GeneratedWorkerMilitiaContract.HunterGuardRadius + 3
                && GeneratedWorkerMilitiaContract.WoodcutterPursuitRadius
                    > GeneratedWorkerMilitiaContract.WoodcutterGuardRadius
                && GeneratedWorkerMilitiaContract.ScanIntervalMilliseconds >= 100
                && GeneratedWorkerMilitiaContract.MoveRefreshMilliseconds >= 250
                && GeneratedWorkerMilitiaContract.HunterAttackCooldownMilliseconds
                    >= 500
                && GeneratedWorkerMilitiaContract.WoodcutterAttackCooldownMilliseconds
                    >= 500
                && GeneratedWorkerMilitiaContract.HoldDurationMilliseconds
                    == 10000;
        }

        private static int GuardRadius(eChimps type)
        {
            return type == eChimps.CHIMP_TYPE_HUNTER
                ? GeneratedWorkerMilitiaContract.HunterGuardRadius
                : GeneratedWorkerMilitiaContract.WoodcutterGuardRadius;
        }

        private static int PursuitRadius(eChimps type)
        {
            return type == eChimps.CHIMP_TYPE_HUNTER
                ? GeneratedWorkerMilitiaContract.HunterPursuitRadius
                : GeneratedWorkerMilitiaContract.WoodcutterPursuitRadius;
        }

        private static int AttackRange(eChimps type)
        {
            return type == eChimps.CHIMP_TYPE_HUNTER
                ? GeneratedWorkerMilitiaContract.HunterAttackRange
                : GeneratedWorkerMilitiaContract.WoodcutterAttackRange;
        }

        private static bool CanEnterMilitiaCombat(eChimps type)
        {
            return WorkerMilitiaSafetyRules.CanEnterCombat(
                type == eChimps.CHIMP_TYPE_HUNTER,
                GeneratedWorkerMilitiaContract.HunterRangeCalibrated);
        }

        private static int AttackCooldown(eChimps type)
        {
            return type == eChimps.CHIMP_TYPE_HUNTER
                ? GeneratedWorkerMilitiaContract.HunterAttackCooldownMilliseconds
                : GeneratedWorkerMilitiaContract.WoodcutterAttackCooldownMilliseconds;
        }

        private static int SimulationNowMilliseconds()
        {
            // SHCDE-SE's deterministic clock stops while paused and advances
            // with the native simulation speed. Keeping the compact wrapping
            // int representation preserves the existing overflow-safe
            // deadline arithmetic while removing all wall-clock behaviour.
            long gameTimeUnits = GameTimeManagerAPI.Instance
                .GetFrameProvider()
                .GetCurrentGameTime();
            return unchecked((int)(gameTimeUnits / 1000L));
        }

        private static bool HasReached(int now, int deadline)
        {
            return unchecked(now - deadline) >= 0;
        }

        private static int RemainingMilliseconds(
            int now,
            int deadline,
            int maximum)
        {
            if (maximum < 0 || HasReached(now, deadline))
            {
                return 0;
            }
            int remaining = unchecked(deadline - now);
            return Math.Min(maximum, Math.Max(0, remaining));
        }

        private static int ElapsedMilliseconds(
            int now,
            int since,
            int maximum)
        {
            if (maximum < 0)
            {
                return 0;
            }
            int elapsed = unchecked(now - since);
            return Math.Min(maximum, Math.Max(0, elapsed));
        }

        private static bool NativeMoveDestinationMatches(
            int workerId,
            int tileX,
            int tileY)
        {
            if (!IsValidMapTile(tileX, tileY)
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    workerId,
                    out var pointer))
            {
                return false;
            }
            ref GameUnit unit = ref pointer.AsRef();
            return (unit.r_TargetTilePositionX == tileX
                    && unit.r_TargetTilePositionY == tileY)
                || (unit.r_TargetTilePositionX2 == tileX
                    && unit.r_TargetTilePositionY2 == tileY);
        }

        private bool IsOperationalLocked()
        {
            return _mapApplied
                && !_networkSuppressed
                && !_selectionQuarantineSuppressed
                && _hunterMoveStateReady
                && !_hunterMoveStateUnavailableForProcess;
        }

        private static bool IsValidMapTile(int tileX, int tileY)
        {
            return tileX >= 0 && tileX <= MaxMapTile
                && tileY >= 0 && tileY <= MaxMapTile;
        }

        private static int ClampMapTile(int tile)
        {
            return Math.Max(0, Math.Min(MaxMapTile, tile));
        }

        private static long DistanceSquared(
            int leftX,
            int leftY,
            int rightX,
            int rightY)
        {
            long dx = (long)leftX - rightX;
            long dy = (long)leftY - rightY;
            return dx * dx + dy * dy;
        }

        private static bool IsEnemyPlayerUnit(int owner, int targetOwner)
        {
            if (owner < 1 || owner > 8
                || targetOwner < 1 || targetOwner > 8
                || owner == targetOwner)
            {
                return false;
            }
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            int ownerTeam = players.GetPlayerTeam(owner);
            int targetTeam = players.GetPlayerTeam(targetOwner);
            // Team zero is the native "no team" value. The extender helper
            // compares raw team numbers, so two unrelated players with team 0
            // are incorrectly reported as allied. Only the same positive team
            // denotes an alliance here.
            return ownerTeam <= 0
                || targetTeam <= 0
                || ownerTeam != targetTeam;
        }

        private static bool IsMilitia(eChimps type)
        {
            return type == eChimps.CHIMP_TYPE_HUNTER
                || type == eChimps.CHIMP_TYPE_WOODCUTTER;
        }

        private static bool CanDamage(eChimps workerType, eChimps targetType)
        {
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            return workerType == eChimps.CHIMP_TYPE_HUNTER
                ? units.GetRangedArrowDamageTo(targetType) > 0
                : units.GetMeleeDamageFromTo(
                    eChimps.CHIMP_TYPE_WOODCUTTER,
                    targetType) > 0;
        }

        private static string UnitName(eChimps type)
        {
            return type == eChimps.CHIMP_TYPE_HUNTER
                ? "hunter"
                : "woodcutter";
        }

        private static string MissionPhaseName(MissionPhase phase)
        {
            switch (phase)
            {
                case MissionPhase.Outbound:
                    return "outbound";
                case MissionPhase.Fighting:
                    return "fighting";
                case MissionPhase.Holding:
                    return "holding";
                case MissionPhase.DirectWorkPending:
                    return "direct_work_pending";
                default:
                    // Reines Protokoll-Hilfsmittel. Es hat den Mod bis zum
                    // 30.08.2026 fuer die ganze Sitzung beenden koennen, nur
                    // weil eine Logzeile geschrieben wurde.
                    return "unknown("
                        + ((int)phase).ToString(CultureInfo.InvariantCulture)
                        + ")";
            }
        }

        private static string TelemetryBoolean(bool value)
        {
            return value ? "true" : "false";
        }

        private static int ThreatPriority(eChimps type)
        {
            switch (type)
            {
                case eChimps.CHIMP_TYPE_ARCHER:
                case eChimps.CHIMP_TYPE_XBOWMAN:
                case eChimps.CHIMP_TYPE_ARAB_BOW:
                case eChimps.CHIMP_TYPE_ARAB_SLINGER:
                case eChimps.CHIMP_TYPE_ARAB_GRENADIER:
                case eChimps.CHIMP_TYPE_BEDOUIN_AMBUSHER:
                case eChimps.CHIMP_TYPE_BEDOUIN_SKIRMISHER:
                    return 0;
                case eChimps.CHIMP_TYPE_LORD:
                case eChimps.CHIMP_TYPE_CATAPULT:
                case eChimps.CHIMP_TYPE_TREBUCHET:
                case eChimps.CHIMP_TYPE_MANGONEL:
                case eChimps.CHIMP_TYPE_BALLISTA:
                case eChimps.CHIMP_TYPE_ARAB_BALLISTA:
                    return 1;
                case eChimps.CHIMP_TYPE_HUNTER:
                case eChimps.CHIMP_TYPE_WOODCUTTER:
                    return 4;
                default:
                    return 2;
            }
        }

        private void ContainOrdinaryEventFailure(
            string stage,
            Exception exception,
            bool releaseSelection)
        {
            string key = "ordinary_event_failure." + stage;
            if (_evidenceLogged.Add(key))
            {
                _warning(
                    "Worker militia contained an ordinary event-path failure "
                    + "without disabling the feature: stage=" + stage
                    + " error="
                    + (exception == null
                        ? "unknown"
                        : exception.GetType().Name)
                    + ". Vanilla input remains available.");
            }
            _inputPackets.Clear();
            _pendingRightClickGesture = null;
            if (!releaseSelection)
            {
                return;
            }
            _selectedWorkerId = 0;
            try
            {
                if (_pendingSelectionWorkerId > 0
                    && _selectionLease != null)
                {
                    RequestOutstandingSelectionCancellation(
                        "contained " + stage,
                        false,
                        false);
                }
                else if (_selectionLease != null)
                {
                    RequestSelectionReleaseAtNativeBoundary(
                        "contained " + stage);
                }
            }
            catch (Exception cleanupException)
            {
                if (_evidenceLogged.Add(key + ".cleanup"))
                {
                    _warning(
                        "Worker militia could not queue optional selection "
                        + "cleanup after " + stage + ": "
                        + cleanupException.GetType().Name
                        + ". No foreign unit was touched.");
                }
            }
        }

        private void FailDeferred(string stage, Exception exception)
        {
            lock (_gate)
            {
                if (_deferredFailure == null)
                {
                    _deferredFailure = new InvalidOperationException(
                        "Worker militia " + stage + " failed",
                        exception);
                    _error(_deferredFailure.ToString());
                }
            }
        }

        private void ThrowDeferredFailure()
        {
            if (_deferredFailure != null)
            {
                throw _deferredFailure;
            }
        }

        private void Dispose(IDisposable subscription)
        {
            if (subscription == null)
            {
                return;
            }
            try
            {
                subscription.Dispose();
            }
            catch (Exception exception)
            {
                _error("Worker militia subscription detach failed: " + exception);
            }
        }
    }
}

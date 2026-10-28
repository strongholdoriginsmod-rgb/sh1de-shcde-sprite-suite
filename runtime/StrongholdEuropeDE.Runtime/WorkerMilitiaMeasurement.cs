using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using SHCDESE.API;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Pure measurement. Reads only; never writes a native field.
    /// </summary>
    /// <remarks>
    /// Built 2026-08-29 after two refuted animation theories (r_AIState, then
    /// r_CurrentSpriteAnimationFrame as a "walking base" - the latter was
    /// disproved by the owner's own run: the hunter learned 0, 5, 11 and 12 in
    /// a single session). Guessing is over. This class dumps every field that
    /// could plausibly drive the visible animation, the command cursor gate and
    /// combat readiness, side by side for a commanded worker and a free
    /// reference of the same type, so the next single run decides all three
    /// open questions instead of feeding another theory.
    ///
    /// Never call anything here from a path that mutates game state.
    /// </remarks>
    internal static class WorkerMilitiaMeasurement
    {
        // Tile-flag array the cone gate at RVA 0x8E398 tests:
        //     test dword [rdi+rdx*4+0x898400],0x10000100   ; rdi = 0x405CD10
        internal static int TileFlagArrayRva { get { return WorkerMilitiaNativeLayout.Current.TileFlagArrayRva; } }
        internal const uint ConeGateMask = 0x10000100u;

        /// <summary>Every field that could drive the drawn animation.</summary>
        internal static string DescribeAnimationFields(int unitId)
        {
            if (unitId <= 0
                || GameUnitManagerAPI.Instance == null
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return "id=" + unitId.ToString(CultureInfo.InvariantCulture)
                    + " missing";
            }
            ref GameUnit u = ref pointer.AsRef();
            return "id=" + unitId.ToString(CultureInfo.InvariantCulture)
                // The sprite group. In the controlled woodcutter pair it was
                // gm=19 for both commanded and free workers, so it did not
                // explain that run's slide. It remains in the trace because a
                // different type/state can still expose a relevant transition.
                + " gm=" + ((int)u.r_GameMaterialIndex).ToString(
                    CultureInfo.InvariantCulture)
                + " anim=" + u.r_AnimationFrame.ToString(
                    CultureInfo.InvariantCulture)
                + " sprite=" + u.r_CurrentSpriteAnimationFrame.ToString(
                    CultureInfo.InvariantCulture)
                + " timer=" + u.r_AnimationTimer.ToString(
                    CultureInfo.InvariantCulture)
                + " ai=" + u.r_AIState.ToString(CultureInfo.InvariantCulture)
                + " role=" + ((int)u.r_AITribeRole).ToString(
                    CultureInfo.InvariantCulture)
                + " dir=" + ((int)u.r_Direction).ToString(
                    CultureInfo.InvariantCulture)
                + " facing=" + ((int)u.r_MovementDirection).ToString(
                    CultureInfo.InvariantCulture)
                + " cmd=" + SeInteropFieldAliases.CommandMode(ref u).ToString(CultureInfo.InvariantCulture)
                + " moving=" + u.r_MovementSubstep.ToString(
                    CultureInfo.InvariantCulture)
                + " path=" + u.r_PathPlanStateBitFlags.ToString(
                    CultureInfo.InvariantCulture)
                + " pathpos=" + u.r_CurrentPathPlanIndex.ToString(
                    CultureInfo.InvariantCulture)
                + " pathlen=" + u.r_PathPlanLength.ToString(
                    CultureInfo.InvariantCulture)
                + " speed=" + u.r_CurrentSpeed.ToString(
                    CultureInfo.InvariantCulture)
                + " speed2=" + u.r_CurrentSpeed2.ToString(
                    CultureInfo.InvariantCulture)
                + " bonus=" + u.r_SpeedBonus.ToString(
                    CultureInfo.InvariantCulture)
                + " wpos=" + u.r_CurrentWorldPositionX.ToString(
                    CultureInfo.InvariantCulture)
                + "," + u.r_CurrentWorldPositionY.ToString(
                    CultureInfo.InvariantCulture)
                + " tile=" + u.r_CurrentTilePositionX.ToString(
                    CultureInfo.InvariantCulture)
                + "," + u.r_CurrentTilePositionY.ToString(
                    CultureInfo.InvariantCulture)
                + " next=" + u.r_NextTilePositionX2.ToString(
                    CultureInfo.InvariantCulture)
                + "," + u.r_NextTilePositionY2.ToString(
                    CultureInfo.InvariantCulture)
                + " tgt=" + u.r_TargetTilePositionX.ToString(
                    CultureInfo.InvariantCulture)
                + "," + u.r_TargetTilePositionY.ToString(
                    CultureInfo.InvariantCulture)
                + " elev=" + u.r_HeightElevation.ToString(
                    CultureInfo.InvariantCulture)
                + " rest=" + u.TimeUntilResting.ToString(
                    CultureInfo.InvariantCulture);
        }

        private const int RangedAttackTargetOffset = 0x340;

        private static unsafe ushort ReadUInt16(ref GameUnit unit, int offset)
        {
            fixed (GameUnit* pointer = &unit)
            {
                return *(ushort*)((byte*)pointer + offset);
            }
        }

        /// <summary>Combat readiness fields, including the engine's own
        /// nearest-enemy distance.</summary>
        internal static string DescribeCombatFields(int unitId)
        {
            if (unitId <= 0
                || GameUnitManagerAPI.Instance == null
                || !GameUnitManagerAPI.Instance.TryGetUnitByIdEx(
                    unitId,
                    out var pointer))
            {
                return "combat=missing";
            }
            ref GameUnit u = ref pointer.AsRef();
            return "nearest_enemy_world="
                + u.r_NearestEnemyWorldTiles.ToString(
                    CultureInfo.InvariantCulture)
                // Raw 16-bit read at +0x340: SE 2.10 types this field UInt32,
                // SE 2.11 UInt16. A typed access binds to one of them and
                // fails to JIT on the other (MissingFieldException).
                + " ranged_target=" + ReadUInt16(ref u, RangedAttackTargetOffset)
                    .ToString(CultureInfo.InvariantCulture)
                + " attacking=" + u.r_AttackingUnitId.ToString(
                    CultureInfo.InvariantCulture)
                + " salvo=" + u.r_ShootingSalvoLeft.ToString(
                    CultureInfo.InvariantCulture)
                + " ctx_target=" + u.r_AI_ContextTargetUnitId.ToString(
                    CultureInfo.InvariantCulture)
                + " last_tribe_cmd="
                + u.r_AI_LastIssuedTribeCommand.ToString(
                    CultureInfo.InvariantCulture)
                + " hp=" + u.r_CurrentHealth.ToString(
                    CultureInfo.InvariantCulture)
                + "/" + u.r_MaxHealth.ToString(CultureInfo.InvariantCulture);
        }

        // 0x18C1A0 - "which unit is the player commanding?" - walks the unit
        // array with these field offsets, all relative to the manager base and
        // all 16-bit. They are the same offsets the census loop uses.
        private const int UnitStride = 0x490;
        private const int UnitAliveOffset = 0x6E4;      // r_AliveState == 2
        private const int UnitBlockedOffset = 0x8F8;    // must be 0
        private const int UnitSelectedOffset = 0x68C;   // r_UnitSelected != 0
        private const int UnitOwnerOffset = 0x6EE;
        private const int UnitTypeOffset = 0x6E6;       // r_UnitChimp
        private static int LocalPlayerRva { get { return WorkerMilitiaNativeLayout.Current.LocalPlayerRva; } }
        internal const int TypeHunter = 6;
        internal const int TypeWoodcutter = 3;

        /// <summary>
        /// The engine's hard-wired command-target priority chain, in its own
        /// order: 0x18C1A0 returns the first of these types that has a
        /// selected unit, and -1 when none does.
        /// </summary>
        private static readonly int[] CommandTargetPriority =
        {
            22, 38, 23, 70, 74, 72, 76, 82, 81, 83, 77, 39, 40, 41, 61,
            24, 25, 26, 27, 28, 78, 79, 80, 84, 85, 5, 29, 30, 37, 71,
            73, 75, 55, 58, 59, 60,
        };

        /// <summary>
        /// Replays 0x18C1A0 in managed code, read-only, straight off the same
        /// memory the engine reads.
        /// </summary>
        /// <remarks>
        /// This is the measurement that decides whether the militia fix works,
        /// because -1 from that function is what makes 0x8E3EA write the
        /// "not possible" cursor. It also shows the damage the unpatched
        /// engine does: with -1 the caller still computes index * 0x490 and
        /// reads BEHIND the unit array, so the tile the cone gate at 0x8E398
        /// tests is not the selected unit's tile at all. Any earlier reading
        /// of "cone_tile_flags" was therefore measuring a different tile than
        /// the engine was.
        ///
        /// Pure Marshal reads of the manager block - no extender call - so it
        /// is safe from the native engine thread as well.
        /// </remarks>
        internal static string DescribeCommandTarget(
            long moduleBase,
            int managerRva)
        {
            if (moduleBase == 0)
            {
                return "cmdtarget=no_module";
            }
            try
            {
                long manager = moduleBase + managerRva;
                int count = Marshal.ReadInt32(new IntPtr(manager));
                if (count < 1 || count > 20000)
                {
                    return "cmdtarget=implausible_count="
                        + count.ToString(CultureInfo.InvariantCulture);
                }
                int localPlayer = Marshal.ReadInt32(
                    new IntPtr(moduleBase + LocalPlayerRva));
                // firstSelectedOfType[type], exactly the table 0x18C1A0 builds
                // on its own stack. 96 entries, matching its 0x180-byte frame.
                var firstOfType = new int[96];
                int selected = 0;
                for (int index = 1; index < count; index++)
                {
                    long unit = manager + ((long)index * UnitStride);
                    if (Marshal.ReadInt16(new IntPtr(unit + UnitAliveOffset))
                            != 2
                        || Marshal.ReadInt16(
                            new IntPtr(unit + UnitBlockedOffset)) != 0
                        || Marshal.ReadInt16(
                            new IntPtr(unit + UnitSelectedOffset)) == 0)
                    {
                        continue;
                    }
                    if (Marshal.ReadInt16(new IntPtr(unit + UnitOwnerOffset))
                        != localPlayer)
                    {
                        // The engine bails out of its whole loop here. Mirror
                        // that, or the replay would disagree with reality.
                        break;
                    }
                    int type = Marshal.ReadInt16(
                        new IntPtr(unit + UnitTypeOffset));
                    if (type < 0 || type >= firstOfType.Length)
                    {
                        continue;
                    }
                    selected++;
                    if (firstOfType[type] == 0)
                    {
                        firstOfType[type] = index;
                    }
                }

                int native = -1;
                int nativeType = -1;
                foreach (int type in CommandTargetPriority)
                {
                    if (firstOfType[type] != 0)
                    {
                        native = firstOfType[type];
                        nativeType = type;
                        break;
                    }
                }
                int militia = 0;
                int militiaType = -1;
                if (firstOfType[TypeHunter] != 0)
                {
                    militia = firstOfType[TypeHunter];
                    militiaType = TypeHunter;
                }
                else if (firstOfType[TypeWoodcutter] != 0)
                {
                    militia = firstOfType[TypeWoodcutter];
                    militiaType = TypeWoodcutter;
                }

                var types = new System.Text.StringBuilder();
                for (int type = 0; type < firstOfType.Length; type++)
                {
                    if (firstOfType[type] == 0)
                    {
                        continue;
                    }
                    if (types.Length > 0)
                    {
                        types.Append(',');
                    }
                    types.Append(type.ToString(CultureInfo.InvariantCulture));
                }

                // What the patched engine answers: the original chain first,
                // the militia only as a last resort.
                int effective = native > 0 ? native : militia;
                return "cmdtarget_selected="
                    + selected.ToString(CultureInfo.InvariantCulture)
                    + " types=[" + (types.Length == 0 ? "none" : types.ToString())
                    + "] stock_answer="
                    + native.ToString(CultureInfo.InvariantCulture)
                    + "(type=" + nativeType.ToString(CultureInfo.InvariantCulture)
                    + ") militia_slot="
                    + militia.ToString(CultureInfo.InvariantCulture)
                    + "(type=" + militiaType.ToString(CultureInfo.InvariantCulture)
                    + ") effective="
                    + (effective > 0
                        ? effective.ToString(CultureInfo.InvariantCulture)
                        : "-1")
                    + " verdict="
                    + (native > 0
                        ? "stock_unit_wins"
                        : militia > 0
                            ? "militia_needs_the_patch"
                            : "nothing_selected");
            }
            catch (Exception)
            {
                return "cmdtarget=unreadable";
            }
        }

        /// <summary>
        /// The cone gate for one unit: its tile and that tile's flag word.
        /// </summary>
        internal static string DescribeConeGate(
            long moduleBase,
            string label,
            int unitId,
            int unitType,
            long tileId)
        {
            if (moduleBase == 0 || unitId <= 0 || tileId < 0)
            {
                return label + "=none";
            }
            string flags = ReadTileFlags(moduleBase, tileId, out uint word)
                ? "0x" + word.ToString("X8", CultureInfo.InvariantCulture)
                : "unreadable";
            return label + "_id="
                + unitId.ToString(CultureInfo.InvariantCulture)
                + " " + label + "_type=" + unitType.ToString(
                    CultureInfo.InvariantCulture)
                + " " + label + "_tile="
                + tileId.ToString(CultureInfo.InvariantCulture)
                + " " + label + "_flags=" + flags
                + " " + label + "_gate="
                + ((word & ConeGateMask) != 0u ? "pass" : "FAIL");
        }

        internal static bool ReadTileFlags(
            long moduleBase,
            long tileId,
            out uint word)
        {
            word = 0u;
            if (moduleBase == 0 || tileId < 0 || tileId > 0xFFFFF)
            {
                return false;
            }
            try
            {
                word = unchecked((uint)Marshal.ReadInt32(new IntPtr(
                    moduleBase + TileFlagArrayRva + (tileId * 4L))));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Flags of an arbitrary tile, for the tile under the cursor.
        /// </summary>
        internal static string DescribeTileFlags(
            long moduleBase,
            string label,
            long tileId)
        {
            string flags = ReadTileFlags(moduleBase, tileId, out uint word)
                ? "0x" + word.ToString("X8", CultureInfo.InvariantCulture)
                : "unreadable";
            return label + "_tile="
                + tileId.ToString(CultureInfo.InvariantCulture)
                + " " + label + "_flags=" + flags
                + " " + label + "_gate="
                + ((word & ConeGateMask) != 0u ? "pass" : "FAIL");
        }

        /// <summary>
        /// Histogram of the distinct tile-flag words carried by the tiles a
        /// set of main-thread unit snapshots stands on, grouped by whether
        /// they pass the cone gate.
        /// This is what decides whether the gate is about terrain at all or
        /// about a per-selection reachability fill.
        /// </summary>
        internal static string DescribeTileFlagHistogram(
            long moduleBase,
            IEnumerable<long> tileIds,
            int maxUnits)
        {
            var passing = new Dictionary<uint, int>();
            var failing = new Dictionary<uint, int>();
            int seen = 0;
            foreach (long tileId in tileIds)
            {
                if (seen >= maxUnits)
                {
                    break;
                }
                if (tileId < 0)
                {
                    continue;
                }
                if (!ReadTileFlags(
                        moduleBase,
                        tileId,
                        out uint word))
                {
                    continue;
                }
                seen++;
                Dictionary<uint, int> bucket =
                    (word & ConeGateMask) != 0u ? passing : failing;
                int count;
                bucket[word] = bucket.TryGetValue(word, out count)
                    ? count + 1
                    : 1;
            }
            return "tiles_sampled="
                + seen.ToString(CultureInfo.InvariantCulture)
                + " passing=[" + Render(passing) + "]"
                + " failing=[" + Render(failing) + "]";
        }

        private static string Render(Dictionary<uint, int> bucket)
        {
            var text = new System.Text.StringBuilder();
            foreach (KeyValuePair<uint, int> pair in bucket)
            {
                if (text.Length > 0)
                {
                    text.Append(' ');
                }
                text.Append("0x");
                text.Append(pair.Key.ToString(
                    "X8",
                    CultureInfo.InvariantCulture));
                text.Append('x');
                text.Append(pair.Value.ToString(CultureInfo.InvariantCulture));
            }
            return text.Length == 0 ? "none" : text.ToString();
        }
    }
}

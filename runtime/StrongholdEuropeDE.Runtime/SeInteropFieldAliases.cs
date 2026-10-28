using System;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using SHCDESE.Interop;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Shared source adapter for the native struct member renames introduced
    /// after SHCDE-SE 2.10.4. Never accepts a renamed field on name alone:
    /// the exact native structure size, field width and byte offset must agree.
    ///
    /// Older militia fields whose meaning changed in 2.14.3 are deliberately
    /// NOT enabled on that layout. This prevents an apparently successful
    /// compiler build from silently altering native gameplay state.
    /// </summary>
    internal static class SeInteropFieldAliases
    {
        private const int GameUnitSize = 1168;
        private const int ResourcesSize = 22588;

        private static readonly bool OldUnitLayout =
            Marshal.SizeOf(typeof(GameUnit)) == GameUnitSize
            && Field(typeof(GameUnit), "N000000A7", typeof(ushort), 0x2A0)
            && Field(typeof(GameUnit), "N0000019A", typeof(uint), 0x29C)
            && Field(typeof(GameUnit), "N000000D0", typeof(ushort), 0x3E8)
            && Field(typeof(GameUnit), "r_SelectionRelevant3", typeof(ushort), 0x354);

        private static readonly bool ModernUnitLayout =
            Marshal.SizeOf(typeof(GameUnit)) == GameUnitSize
            && Field(typeof(GameUnit), "r_SelectionAllowed", typeof(ushort), 0x2A0)
            && Field(typeof(GameUnit), "r_IsKilledByProjectile", typeof(ushort), 0x29C)
            && Field(typeof(GameUnit), "r_InterestingTodo4MaybeRandomPathing",
                typeof(ushort), 0x29E)
            && Field(typeof(GameUnit), "r_AIObjectiveState", typeof(ushort), 0x354)
            && Field(typeof(GameUnit), "r_ChimpName1", typeof(byte), 0x3E8);

        private static readonly bool OldSiegeLayout =
            Marshal.SizeOf(typeof(GamePlayerResources)) == ResourcesSize
            && Field(typeof(GamePlayerResources),
                "r_AISiegePlayerIdTarget", typeof(uint), 11224);

        private static readonly bool ModernSiegeLayout =
            Marshal.SizeOf(typeof(GamePlayerResources)) == ResourcesSize
            && Field(typeof(GamePlayerResources),
                "r_SiegeAttackTargetPlayerId", typeof(uint), 11224);

        internal static bool SupportsLegacyWorkerLayout
        {
            get { return OldUnitLayout; }
        }

        internal static bool SupportsSiegeTarget
        {
            get { return OldSiegeLayout || ModernSiegeLayout; }
        }

        private static bool Field(Type type, string name, Type expectedType, int offset)
        {
            FieldInfo member = type.GetField(name,
                BindingFlags.Instance | BindingFlags.Public);
            if (member == null || member.FieldType != expectedType)
            {
                return false;
            }
            try
            {
                return Marshal.OffsetOf(type, name).ToInt32() == offset;
            }
            catch (ArgumentException)
            {
                return false;
            }
        }

        private static void Require(bool verified, string lane)
        {
            if (!verified)
            {
                throw new NotSupportedException(
                    "SE native interop layout is not proven: " + lane);
            }
        }

        internal static ref ushort CommandMode(ref GameUnit unit)
        {
            // Modern r_SelectionAllowed may not mean legacy worker command mode.
            // Keep unsafe worker-control mutations disabled on that layout.
            Require(OldUnitLayout, "worker_command_mode_legacy_only");
            return ref Unsafe.Add(ref Unsafe.As<GameUnit, ushort>(ref unit), 0x2A0 / 2);
        }

        internal static ref uint SelectionBlocker(ref GameUnit unit)
        {
            // 2.14.3 split this former uint into two independent ushort
            // fields with different semantics. No legacy worker logic
            // is allowed to reinterpret the combined value.
            Require(OldUnitLayout, "selection_blocker_legacy_only");
            return ref Unsafe.Add(ref Unsafe.As<GameUnit, uint>(ref unit), 0x29C / 4);
        }

        internal static ref ushort SelectionRelevant(ref GameUnit unit)
        {
            Require(OldUnitLayout, "selection_relevant_legacy_only");
            return ref Unsafe.Add(ref Unsafe.As<GameUnit, ushort>(ref unit), 0x354 / 2);
        }

        internal static ref ushort WorkerName(ref GameUnit unit)
        {
            // Former ushort changed into r_ChimpName1:byte. Keep the
            // worker-name feature closed until its new representation
            // has been independently validated.
            Require(OldUnitLayout, "worker_name_legacy_only");
            return ref Unsafe.Add(ref Unsafe.As<GameUnit, ushort>(ref unit), 0x3E8 / 2);
        }

        internal static unsafe ref uint SiegeTarget(GamePlayerResources* resources)
        {
            if (resources == null)
            {
                throw new ArgumentNullException("resources");
            }
            Require(OldSiegeLayout || ModernSiegeLayout, "ai_siege_target");
            ref GamePlayerResources native = ref *resources;
            return ref Unsafe.Add(ref Unsafe.As<GamePlayerResources, uint>(ref native), 11224 / 4);
        }
    }
}

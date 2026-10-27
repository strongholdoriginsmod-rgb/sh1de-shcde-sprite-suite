using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using HarmonyLib;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// A militia hunter keeps looking like a hunter, a militia woodcutter like
    /// a woodcutter (user decision 2026-09-28), although the engine draws them
    /// as archer and maceman.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Where: GameMap.addUpdateChimp(objectID, …, file, image, …) is the one
    /// managed call through which every unit sprite reaches Unity (GameMap
    /// reads it from the native draw buffer). A prefix swaps file (GM group)
    /// and image (frame) for units the militia registry marks.
    /// </para>
    /// <para>
    /// Frame rule (measured 2026-09-28 on CrusaderDE.dll 2.80): image =
    /// 8*phase + 1 + facing, facing 0..7; every animation is a base plus a
    /// byte table of phase steps (e.g. archer shot: base 0xF9, table
    /// 0x32C298; hunter shot: base 0x301, table 0x330090). The tables below
    /// map phase ranges of the soldier onto the worker's range with the same
    /// meaning and keep the facing:
    /// </para>
    /// <list type="bullet">
    /// <item>archer walk 0-15 and run 16-31 = hunter walk/stalk, same phases</item>
    /// <item>archer shots 32-79 (8-phase draw+release sequences 32/48/60/72,
    /// 4-phase recovers 56/68) = hunter shot 97-120</item>
    /// <item>idle poses 80-87 are the same slots in both groups</item>
    /// <item>archer dig 131-146 and deaths 147-218 (corpses 170/194/218) =
    /// hunter butcher 121-136 and deaths 137-208: ten phases lower</item>
    /// <item>maceman swing 65-76 (table 0x32D498) = woodcutter chop 96-107
    /// (base 0x2F9, table 0x330378); deaths end on the corpse phase in both</item>
    /// </list>
    /// <para>
    /// A soldier phase outside every range falls back to a standing frame of
    /// the worker in the same facing; the first few are logged so the table
    /// can be completed from a play log.
    /// </para>
    /// </remarks>
    internal sealed class WorkerMilitiaAppearance
    {
        // { soldier phase from, to, worker phase from, to } (inclusive, linear)
        internal static readonly int[][] HunterFromArcher =
        {
            new[] { 0, 15, 0, 15 },
            new[] { 16, 31, 16, 31 },
            new[] { 32, 39, 97, 120 },
            new[] { 40, 47, 104, 111 },
            new[] { 48, 55, 97, 120 },
            new[] { 56, 59, 113, 120 },
            new[] { 60, 67, 97, 120 },
            new[] { 68, 71, 113, 120 },
            new[] { 72, 79, 97, 120 },
            new[] { 80, 87, 80, 87 },
            new[] { 111, 126, 0, 15 },
            new[] { 130, 130, 120, 120 },
            new[] { 131, 218, 121, 208 },
        };

        internal static readonly int[][] WoodcutterFromMaceman =
        {
            new[] { 0, 15, 0, 15 },
            new[] { 16, 31, 0, 15 },
            new[] { 65, 76, 96, 107 },
            new[] { 103, 118, 96, 107 },
            new[] { 119, 142, 123, 146 },
            new[] { 143, 166, 147, 170 },
            new[] { 167, 190, 147, 170 },
        };

        internal const int HunterIdlePhase = 80;
        internal const int WoodcutterIdlePhase = 0;
        private const int MaxLoggedFallbacks = 12;

        private static WorkerMilitiaAppearance _instance;
        private static int _archerFile;
        private static int _macemanFile;
        private static int _hunterFile;
        private static int _woodcutterFile;

        private readonly Harmony _harmony;
        private readonly Action<string> _info;
        private readonly HashSet<string> _fallbacks = new HashSet<string>(StringComparer.Ordinal);
        private MethodInfo _target;
        private static FieldInfo _gmSpritesField;
        private volatile bool _sawMilitiaDrawn;

        internal WorkerMilitiaAppearance(Harmony harmony, Action<string> info)
        {
            _harmony = harmony;
            _info = info;
        }

        internal bool Prepare(out string failure)
        {
            _target = AccessTools.Method(typeof(GameMap), "addUpdateChimp");
            if (_target == null)
            {
                failure = "GameMap.addUpdateChimp not found";
                return false;
            }
            var names = new List<string>();
            foreach (ParameterInfo parameter in _target.GetParameters())
            {
                names.Add(parameter.Name);
            }
            if (names.Count < 8 || names[0] != "_objectID" || names[6] != "file" || names[7] != "image")
            {
                failure = "GameMap.addUpdateChimp signature changed";
                return false;
            }
            _gmSpritesField = AccessTools.Field(typeof(spriteLoader), "gmSprites");
            if (_gmSpritesField == null || _gmSpritesField.FieldType != typeof(UnityEngine.Sprite[][]))
            {
                failure = "spriteLoader.gmSprites changed";
                return false;
            }
            _archerFile = (int)Enums.GM.GM_BODY_ARCHER;
            _macemanFile = (int)Enums.GM.GM_BODY_MACEMAN;
            _hunterFile = (int)Enums.GM.GM_BODY_HUNTER;
            _woodcutterFile = (int)Enums.GM.GM_BODY_WOODCUTTER;
            failure = null;
            return true;
        }

        internal void Apply()
        {
            _instance = this;
            _harmony.Patch(_target, prefix: new HarmonyMethod(typeof(WorkerMilitiaAppearance)
                .GetMethod("DrawPrefix", BindingFlags.NonPublic | BindingFlags.Static)));
        }

        internal void Rollback()
        {
            if (_target != null)
            {
                _harmony.Unpatch(_target, HarmonyPatchType.Prefix, _harmony.Id);
            }
            if (ReferenceEquals(_instance, this))
            {
                _instance = null;
            }
        }

        private static void DrawPrefix(int _objectID, ref int file, ref int image)
        {
            if (_objectID <= 0 || _objectID >= WorkerMilitiaTroopPanel.MilitiaKind.Length)
            {
                return;
            }
            byte kind = WorkerMilitiaTroopPanel.MilitiaKind[_objectID];
            if (kind == WorkerMilitiaTroopPanel.KindNone)
            {
                return;
            }
            WorkerMilitiaAppearance self = _instance;
            if (self == null)
            {
                return;
            }
            try
            {
                int workerFile;
                int mapped;
                if (kind == WorkerMilitiaTroopPanel.KindHunter && file == _archerFile)
                {
                    workerFile = _hunterFile;
                    mapped = Remap(image, HunterFromArcher, HunterIdlePhase, self, "archer");
                    mapped = Existing(workerFile, mapped, HunterIdlePhase);
                }
                else if (kind == WorkerMilitiaTroopPanel.KindWoodcutter && file == _macemanFile)
                {
                    workerFile = _woodcutterFile;
                    mapped = Remap(image, WoodcutterFromMaceman, WoodcutterIdlePhase, self, "maceman");
                    mapped = Existing(workerFile, mapped, WoodcutterIdlePhase);
                }
                else
                {
                    return;
                }
                if (mapped < 0)
                {
                    // No worker frame at all: the soldier frame beats an
                    // invisible militiaman.
                    return;
                }
                file = workerFile;
                image = mapped;
                if (!self._sawMilitiaDrawn)
                {
                    self._sawMilitiaDrawn = true;
                    self._info("SEDE_RUNTIME_V1|event=worker_militia_appearance|status=first_remap|object="
                        + _objectID.ToString(CultureInfo.InvariantCulture));
                }
            }
            catch (Exception)
            {
                // Drawing must never fail because of the militia.
            }
        }

        /// <summary>
        /// A few block-edge frames do not exist in the worker group (e.g.
        /// woodcutter 128): an empty slot would draw nothing. Then the
        /// worker's standing frame in the same facing, else -1.
        /// </summary>
        private static int Existing(int file, int image, int idlePhase)
        {
            if (Has(file, image))
            {
                return image;
            }
            int idle = idlePhase * 8 + 1 + ((image - 1) & 7);
            return Has(file, idle) ? idle : -1;
        }

        private static bool Has(int file, int image)
        {
            spriteLoader loader = spriteLoader.instance;
            if ((object)loader == null)
            {
                return false;
            }
            var groups = _gmSpritesField.GetValue(loader) as UnityEngine.Sprite[][];
            if (groups == null || file < 0 || file >= groups.Length)
            {
                return false;
            }
            UnityEngine.Sprite[] frames = groups[file];
            return frames != null && image >= 0 && image < frames.Length && frames[image] != null;
        }

        internal static int Remap(int image, int[][] table, int idlePhase, WorkerMilitiaAppearance log, string from)
        {
            if (image < 1)
            {
                return image;
            }
            int phase = (image - 1) >> 3;
            int facing = (image - 1) & 7;
            foreach (int[] row in table)
            {
                if (phase < row[0] || phase > row[1])
                {
                    continue;
                }
                int span = row[1] - row[0];
                int target = span == 0
                    ? row[2]
                    : row[2] + (int)Math.Round((phase - row[0]) * (double)(row[3] - row[2]) / span);
                return target * 8 + 1 + facing;
            }
            if (log != null && log._fallbacks.Count < MaxLoggedFallbacks
                && log._fallbacks.Add(from + "." + phase.ToString(CultureInfo.InvariantCulture)))
            {
                log._info("SEDE_RUNTIME_V1|event=worker_militia_appearance|status=unmapped_phase|from="
                    + from + "|phase=" + phase.ToString(CultureInfo.InvariantCulture));
            }
            return idlePhase * 8 + 1 + facing;
        }
    }
}

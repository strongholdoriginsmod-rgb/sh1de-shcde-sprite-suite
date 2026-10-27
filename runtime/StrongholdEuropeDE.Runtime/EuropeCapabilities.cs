using System;
using System.Collections.Generic;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// What this build can actually do, decided per lane rather than globally.
    /// </summary>
    /// <remarks>
    /// This exists because of a real failure, twice. The build guard verified
    /// every pinned prerequisite as one indivisible block: any single mismatch
    /// threw, <c>Awake</c> aborted, and the whole companion went dark. That
    /// would be acceptable if the companion were the only thing running - but
    /// it is not. The script extender applies the atlas overrides on its own,
    /// before and independently of us. So a companion that fails closed leaves
    /// the game with our replaced sprites and none of the runtime work that
    /// finishes them, which is exactly the black screen after the Firefly logo.
    ///
    /// The fix is not to fail open. It is to stop treating unrelated
    /// dependencies as one decision. R3 carries the extender's native detours
    /// as observables and is needed by precisely one lane, the farm placement
    /// rule. If R3 is missing or mismatched, that lane must not run - and every
    /// other lane must be entirely unaffected.
    ///
    /// Each capability is decided once, at startup, and never re-probed: a lane
    /// that was told it may run must not have the ground move under it later.
    /// </remarks>
    internal sealed class EuropeCapabilities
    {
        private readonly List<string> _report;

        private EuropeCapabilities(
            bool core,
            string coreFailure,
            bool r3,
            string r3Failure,
            List<string> report)
        {
            Core = core;
            CoreFailure = coreFailure;
            R3 = r3;
            R3Failure = r3Failure;
            _report = report;
        }

        /// <summary>
        /// The dependencies without which nothing can run: the game assembly,
        /// the extender, BepInEx, Harmony and the Unity core module. There is
        /// no useful degraded mode below this line.
        /// </summary>
        internal bool Core { get; }

        internal string CoreFailure { get; }

        /// <summary>R3 observables - required only by the farm placement lane.</summary>
        internal bool R3 { get; }

        internal string R3Failure { get; }

        /// <summary>
        /// The farm rule subscribes to a placement observable, so it runs only
        /// when both the core and R3 verified.
        /// </summary>
        internal bool FarmPlacement
        {
            get { return Core && R3; }
        }

        /// <summary>
        /// Worker militia uses map and melee observables in addition to the
        /// extender's unit/tribe APIs.
        /// </summary>
        internal bool WorkerMilitia
        {
            get { return Core && R3; }
        }

        /// <summary>
        /// The dock measurement subscribes to the same placement observable and
        /// to the map-start observable, so it runs under exactly the same
        /// condition as the farm rule.
        /// </summary>
        /// <remarks>
        /// Deliberately its own property rather than a reuse of
        /// <see cref="FarmPlacement"/>: the two lanes are separate decisions and
        /// have to stay separately switchable. The body is the same today, and
        /// that is a fact about the dependencies, not about the lanes.
        /// </remarks>
        internal bool DockPlacement
        {
            get { return Core && R3; }
        }

        /// <summary>
        /// Foliage, audio, music routing and the roster reach the extender
        /// directly and need nothing beyond the core.
        /// </summary>
        internal bool CoreLanes
        {
            get { return Core; }
        }

        /// <summary>One line per probed capability, for the runtime log.</summary>
        internal string Report
        {
            get
            {
                var builder = new StringBuilder("SEDE_RUNTIME_V1|event=capabilities");
                foreach (string entry in _report)
                {
                    builder.Append('|').Append(entry);
                }

                return builder.ToString();
            }
        }

        /// <summary>
        /// Probe every capability. Never throws: a probe that fails records why
        /// and leaves the corresponding capability false, so the caller decides
        /// what that means rather than being unwound by an exception.
        /// </summary>
        internal static EuropeCapabilities Probe()
        {
            var report = new List<string>();
            string coreFailure = null;
            bool core;
            try
            {
                RuntimeBuildGuard.VerifyCoreReportingDrift();
                core = true;
                report.Add("core=ok");
            }
            catch (Exception exception)
            {
                core = false;
                coreFailure = exception.Message;
                report.Add("core=failed");
            }

            string r3Failure = null;
            bool r3;
            try
            {
                RuntimeBuildGuard.VerifyOptionalReportingDrift("r3");
                r3 = true;
                report.Add("r3=ok");
            }
            catch (Exception exception)
            {
                r3 = false;
                r3Failure = exception.Message;
                report.Add("r3=failed");
            }

            // Identity drift never disables a lane by itself; it is reported
            // once so a bug report says which combination was running.
            string unverified = RuntimeBuildGuard.DriftReport();
            report.Add(unverified.Length == 0
                ? "combination=verified"
                : "combination=unverified|unverified=" + unverified);
            report.Add(core && r3 ? "farm_placement=ok" : "farm_placement=disabled");
            report.Add(core && r3 ? "worker_militia=ok" : "worker_militia=disabled");
            return new EuropeCapabilities(core, coreFailure, r3, r3Failure, report);
        }
    }
}

#if ASSET_STREAM_HARNESS
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    internal static class AssetStreamDependencyFreeHarness
    {
        private const long Mib = 1024L * 1024;
        private const long Gib = 1024L * 1024 * 1024;
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
        private static readonly object HarnessNeutralMask = new object();
        private static int passed;

        private static int Main()
        {
            Run("canonical index + atlas.v2", TestCanonicalDocuments);
            Run("canonical vanilla omissions", TestVanillaOmissions);
            Run("exact material binding modes", TestMaterialBindingModes);
            Run("strict path, POT, LF gates", TestStrictGates);
            Run("exact accounting + policy", TestAccountingAndPolicy);
            Run("admission reasons + two probes", TestAdmission);
            Run("second admission prevents publish", TestSecondAdmissionDenial);
            Run("success, restore, delayed release", TestControllerLifecycle);
            Run("one global cleanup scan per release wave", TestGlobalUnloadBatch);
            Run("map PRE activates before getters and POST deduplicates", TestMapStartGate);
            Run("restore precedes scene reset and epoch summary", TestEpochRestoreOrdering);
            Run("off-main epoch CAS deduplicates and rejects stale requests",
                TestOffMainEpochQueue);
            Run("battlement masks select top or flattened ground anchor",
                TestBattlementOverlayAnchors);
            Run("off-main getter handoff ignores held main timeline",
                TestOffMainQueueDoesNotWaitForTimeline);
            Run("epoch close drains admitted off-main request exactly once",
                TestOffMainEpochCloseBarrier);
            Run("page mask preserves all seven chop materials and foreign state",
                TestPageMaskOwnership);
            Run("all-group page-mask telemetry is bounded and fail-visible",
                TestPageMaskRouteDiagnostics);
            Run("central materials retain exact owned masks until safe release",
                TestCentralMaterialMaskAudit);
            AssetStreamBc7DependencyFreeHarness.Register(Run);
            Console.WriteLine("AssetStream harness: " + passed + "/27 passed");
            return 0;
        }

        private static void TestBattlementOverlayAnchors()
        {
            int[] imageIds = { 1, 2, 3, 4, 11, 12, 13, 14, 27 };
            float[] sourceHeights = { 98, 165, 132, 146, 217, 210, 233, 220, 287 };
            float[] groundAnchors = { 138, 183, 161, 226, 236, 235, 255, 260, 305 };
            for (int index = 0; index < imageIds.Length; index++)
            {
                float normal;
                True(
                    BattlementOverlayAnchor.TryResolvePivotY(
                        BattlementOverlayAnchor.CastleAnimationsGm,
                        imageIds[index],
                        false,
                        sourceHeights[index],
                        false,
                        out normal),
                    "reviewed foreground mask is routed in normal view");
                Equal(1f, normal, "normal view aligns the battlement top");

                float flattened;
                True(
                    BattlementOverlayAnchor.TryResolvePivotY(
                        BattlementOverlayAnchor.CastleAnimationsGm,
                        imageIds[index],
                        false,
                        sourceHeights[index],
                        true,
                        out flattened),
                    "reviewed foreground mask is routed in flattened view");
                True(
                    Math.Abs(
                        groundAnchors[index]
                        - flattened * sourceHeights[index]) <= 0.001f,
                    "flattened view retains Crusader's absolute ground anchor");
            }

            float ignored;
            True(
                !BattlementOverlayAnchor.TryResolvePivotY(
                    BattlementOverlayAnchor.CastleAnimationsGm,
                    5,
                    false,
                    98,
                    false,
                    out ignored),
                "unrelated anim_castle frame is untouched");
            True(
                !BattlementOverlayAnchor.TryResolvePivotY(
                    BattlementOverlayAnchor.CastleAnimationsGm,
                    1,
                    true,
                    98,
                    false,
                    out ignored),
                "alternate frames are untouched");
            True(
                !BattlementOverlayAnchor.TryResolvePivotY(
                    BattlementOverlayAnchor.CastleAnimationsGm,
                    1,
                    false,
                    99,
                    false,
                    out ignored),
                "unreviewed source geometry fails open");
        }

        private static void TestPageMaskRouteDiagnostics()
        {
            var renderer = new object();
            var diagnostics = new AssetStreamPageMaskProbeDiagnostics();
            diagnostics.Reset(7);
            AssetStreamPageMaskProbeEvent observed;

            AssetStreamPageMaskProbeSnapshot first = MaskRouteSnapshot(
                7, 42, renderer, "sprite-a", "material-a", "shader-a",
                "page-a", "page-a", 100);
            True(
                diagnostics.TryObserve(first, first, "", out observed),
                "first required route emits an initial observation");
            Equal("group_first_observed", observed.Reason, "initial reason");
            True(!observed.Anomaly, "initial route is not anomalous");

            AssetStreamPageMaskProbeSnapshot imageOnly = MaskRouteSnapshot(
                7, 42, renderer, "sprite-b", "material-a", "shader-a",
                "page-a", "page-a", 101);
            True(
                !diagnostics.TryObserve(
                    imageOnly, imageOnly, "", out observed),
                "image-only changes are deduplicated");

            AssetStreamPageMaskProbeSnapshot pageBefore = MaskRouteSnapshot(
                7, 42, renderer, "sprite-c", "material-a", "shader-a",
                "page-b", "page-a", 102);
            AssetStreamPageMaskProbeSnapshot pageAfter = MaskRouteSnapshot(
                7, 42, renderer, "sprite-c", "material-a", "shader-a",
                "page-b", "page-b", 102);
            True(
                diagnostics.TryObserve(
                    pageBefore, pageAfter, "", out observed),
                "atlas page correction is observed");
            Equal("mask_corrected", observed.Reason, "page correction reason");
            Equal(1, diagnostics.Corrections, "page correction counter");

            AssetStreamPageMaskProbeSnapshot driftBefore = MaskRouteSnapshot(
                7, 42, renderer, "sprite-c", "material-a", "shader-a",
                "page-b", "foreign-mask", 102);
            True(
                diagnostics.TryObserve(
                    driftBefore, pageAfter, "", out observed),
                "external block drift is observed");
            Equal(
                "external_drift_between_calls",
                observed.Reason,
                "external drift reason");
            True(observed.Anomaly, "external drift is anomalous");

            AssetStreamPageMaskProbeSnapshot mismatch = MaskRouteSnapshot(
                7, 42, renderer, "sprite-c", "material-a", "shader-a",
                "page-b", "wrong-after", 102);
            True(
                diagnostics.TryObserve(
                    pageAfter, mismatch, "", out observed),
                "postfix mismatch is observed");
            Equal("postfix_mismatch", observed.Reason, "mismatch reason");
            Equal(1, diagnostics.PostfixMismatches, "postfix mismatch counter");

            var singlePageRenderer = new object();
            AssetStreamPageMaskProbeSnapshot missingSinglePageRoute =
                MissingRequiredRouteSnapshot(
                    7,
                    43,
                    singlePageRenderer,
                    "body_baker",
                    77);
            True(
                diagnostics.ShouldObserve(
                    43,
                    singlePageRenderer,
                    true,
                    string.Empty),
                "required single-page groups are observed without a route");
            True(
                diagnostics.TryObserve(
                    missingSinglePageRoute,
                    missingSinglePageRoute,
                    "",
                    out observed),
                "missing single-page route is a postfix mismatch");
            Equal("postfix_mismatch", observed.Reason,
                "missing single-page route reason");
            Equal(2, diagnostics.PostfixMismatches,
                "missing route remains visible in mismatch counter");

            diagnostics.Reset(8);
            AssetStreamPageMaskProbeSnapshot materialA = MaskRouteSnapshot(
                8, 42, renderer, "sprite-a", "material-a", "shader-a",
                "page-a", "page-a", 100);
            diagnostics.TryObserve(materialA, materialA, "", out observed);
            AssetStreamPageMaskProbeSnapshot materialB = MaskRouteSnapshot(
                8, 42, renderer, "sprite-a", "material-b", "shader-b",
                "page-a", "page-a", 100);
            True(
                !diagnostics.TryObserve(
                    materialB, materialB, "", out observed),
                "material transition without a mask correction stays quiet");
            True(
                diagnostics.TryObserve(
                    materialB,
                    materialB,
                    "InvalidOperationException",
                    out observed),
                "route exception is observed even without state drift");
            Equal("route_exception", observed.Reason, "exception reason");

            var replacementRenderer = new object();
            AssetStreamPageMaskProbeSnapshot reused = MaskRouteSnapshot(
                8, 42, replacementRenderer, "sprite-a", "material-a", "shader-a",
                "page-a", "page-a", 100);
            True(
                diagnostics.TryObserve(reused, reused, "", out observed),
                "renderer instance-id reuse starts a new observation");
            True(observed.RendererIdReused, "renderer reuse is explicit");
            Equal("renderer_id_reused", observed.Reason, "renderer reuse reason");

            diagnostics.Reset(9);
            int emitted = 0;
            for (int index = 0;
                index < AssetStreamPageMaskProbeDiagnostics.MaximumLogsPerEpoch + 2;
                index++)
            {
                string page = (index & 1) == 0 ? "page-a" : "page-b";
                AssetStreamPageMaskProbeSnapshot sampleBefore = MaskRouteSnapshot(
                    9, 42, renderer, "sprite", "material", "shader",
                    page, "wrong", index);
                AssetStreamPageMaskProbeSnapshot sampleAfter = MaskRouteSnapshot(
                    9, 42, renderer, "sprite", "material", "shader",
                    page, page, index);
                if (diagnostics.TryObserve(
                        sampleBefore,
                        sampleAfter,
                        "",
                        out observed))
                {
                    emitted++;
                }
            }
            Equal(
                AssetStreamPageMaskProbeDiagnostics.MaximumLogsPerEpoch,
                emitted,
                "event output is capped per epoch");
            Equal(
                AssetStreamPageMaskProbeDiagnostics.MaximumLogsPerEpoch + 2,
                diagnostics.Events,
                "counter retains suppressed transitions");
            Equal(
                AssetStreamPageMaskProbeDiagnostics.MaximumLogsPerEpoch + 2,
                diagnostics.Corrections,
                "correction counter retains suppressed details");
            Equal(2, diagnostics.Dropped, "suppressed event counter");
            diagnostics.Reset(10);
            Equal(0, diagnostics.Events, "epoch reset clears event count");
            Equal(0, diagnostics.Corrections, "epoch reset clears correction count");
            Equal(0, diagnostics.PostfixMismatches,
                "epoch reset clears mismatch count");
            Equal(0, diagnostics.Anomalies, "epoch reset clears anomaly count");
            Equal(0, diagnostics.Dropped, "epoch reset clears dropped count");

            MaskRouteRetentionFixture retention = CreateMaskRouteRetentionFixture();
            for (int attempt = 0;
                attempt < 4 && retention.Renderer.IsAlive;
                attempt++)
            {
                GC.Collect();
                GC.WaitForPendingFinalizers();
                GC.Collect();
            }
            True(
                !retention.Renderer.IsAlive,
                "diagnostic state does not root a renderer");
            GC.KeepAlive(retention.Diagnostics);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static MaskRouteRetentionFixture CreateMaskRouteRetentionFixture()
        {
            var diagnostics = new AssetStreamPageMaskProbeDiagnostics();
            diagnostics.Reset(11);
            var renderer = new object();
            AssetStreamPageMaskProbeSnapshot snapshot = MaskRouteSnapshot(
                11, 73, renderer, "sprite", "material", "shader",
                "page-a", "page-a", 1);
            AssetStreamPageMaskProbeEvent observed;
            diagnostics.TryObserve(snapshot, snapshot, "", out observed);
            return new MaskRouteRetentionFixture(
                diagnostics,
                new WeakReference(renderer));
        }

        private sealed class MaskRouteRetentionFixture
        {
            internal MaskRouteRetentionFixture(
                AssetStreamPageMaskProbeDiagnostics diagnostics,
                WeakReference renderer)
            {
                Diagnostics = diagnostics;
                Renderer = renderer;
            }

            internal AssetStreamPageMaskProbeDiagnostics Diagnostics {
                get;
                private set;
            }
            internal WeakReference Renderer { get; private set; }
        }

        private static AssetStreamPageMaskProbeSnapshot MaskRouteSnapshot(
            long epoch,
            int rendererId,
            object renderer,
            string sprite,
            string material,
            string shader,
            string expectedMask,
            string blockMask,
            int image)
        {
            return new AssetStreamPageMaskProbeSnapshot(
                epoch,
                rendererId,
                renderer,
                false,
                "body_jester",
                true,
                "body_jester",
                sprite,
                material,
                shader,
                expectedMask,
                true,
                true,
                blockMask,
                true,
                "material-mask",
                17,
                image,
                2,
                false,
                8,
                0);
        }

        private static AssetStreamPageMaskProbeSnapshot MissingRequiredRouteSnapshot(
            long epoch,
            int rendererId,
            object renderer,
            string group,
            int image)
        {
            return new AssetStreamPageMaskProbeSnapshot(
                epoch,
                rendererId,
                renderer,
                false,
                group,
                true,
                string.Empty,
                "sprite-single-page",
                "material-single-page",
                "shader-team-colour",
                "null",
                false,
                true,
                "black-neutral",
                true,
                "page-mask",
                19,
                image,
                1,
                false,
                0,
                0);
        }

        private static void TestOffMainEpochCloseBarrier()
        {
            var queue = new AssetStreamOffMainRequestQueue(4);
            queue.OpenEpoch(12);
            using (var admitted = new ManualResetEventSlim(false))
            using (var release = new ManualResetEventSlim(false))
            {
                queue.AfterAdmissionForTest = delegate
                {
                    admitted.Set();
                    release.Wait();
                };
                bool enqueued = false;
                Exception workerFailure = null;
                var worker = new Thread(delegate()
                {
                    try { enqueued = queue.TryEnqueue(2, 12); }
                    catch (Exception exception) { workerFailure = exception; }
                });
                worker.IsBackground = true;
                worker.Start();
                True(admitted.Wait(TimeSpan.FromSeconds(2)),
                    "worker entered admitted enqueue window");

                IList<int> drained = null;
                Exception closerFailure = null;
                var closer = new Thread(delegate()
                {
                    try { drained = queue.CloseEpochAndDrain(12); }
                    catch (Exception exception) { closerFailure = exception; }
                });
                closer.IsBackground = true;
                closer.Start();
                try
                {
                    True(!closer.Join(100),
                        "epoch close waits for admitted enqueue");
                }
                finally
                {
                    release.Set();
                }
                True(worker.Join(2000), "admitted worker completes");
                True(closer.Join(2000), "epoch close completes");
                if (workerFailure != null)
                {
                    throw new InvalidOperationException(
                        "admitted worker failed",
                        workerFailure);
                }
                if (closerFailure != null)
                {
                    throw new InvalidOperationException(
                        "epoch closer failed",
                        closerFailure);
                }
                True(enqueued, "CAS-admitted request was enqueued");
                Equal(1, drained.Count, "admitted request drained once");
                Equal(2, drained[0], "drain retains admitted GM");
                Equal(0, queue.CloseEpochAndDrain(12).Count,
                    "closed epoch cannot drain a second terminal");
                True(!queue.TryEnqueue(2, 12),
                    "closed epoch rejects a delayed getter");
                Equal(0, queue.ApproximateCount,
                    "closed epoch leaves no stale request");
            }
        }

        private static void TestPageMaskOwnership()
        {
            var equalMaskA = new HarnessEqualMask();
            var equalMaskB = new HarnessEqualMask();
            var exactMasks = new AssetStreamReferenceCountSet<object>();
            exactMasks.Add(equalMaskA);
            exactMasks.Add(equalMaskA);
            True(!exactMasks.Contains(equalMaskB),
                "owned-mask registry uses exact reference identity");
            Equal(2, exactMasks.Count(equalMaskA),
                "owned-mask registry counts duplicate group/page ownership");
            True(exactMasks.Remove(equalMaskA)
                    && exactMasks.Contains(equalMaskA),
                "duplicate group/page registrations retain mask ownership by count");
            True(exactMasks.Remove(equalMaskA)
                    && !exactMasks.Contains(equalMaskA),
                "last group/page unregister retires exact mask ownership");

            var ownership = new AssetStreamPageMaskOwnership<object>();
            var pageZero = new object();
            var pageOne = new object();
            var ownedMasks = new AssetStreamReferenceCountSet<object>();
            ownedMasks.Add(pageZero);
            ownedMasks.Add(pageOne);
            int[] chopFeet = { 0, 4, 8, 12, 16, 20, 24 };
            for (int slot = 0; slot < chopFeet.Length; slot++)
            {
                var vanillaMask = new object();
                var material = new HarnessMaskMaterial(
                    true,
                    vanillaMask,
                    0.03125f + slot);
                var renderer = new HarnessMaskRenderer(100 + slot, material)
                {
                    Colour = "team-" + slot,
                    Alpha = 0.25f + slot * 0.1f
                };
                var foreignVector = new object();
                renderer.Block.Add("_ForeignVector", foreignVector);
                object expectedPage = slot % 2 == 0 ? pageZero : pageOne;
                HarnessApplyPageMask(
                    ownership,
                    ownedMasks,
                    renderer,
                    true,
                    expectedPage);

                True(ReferenceEquals(material, renderer.SharedMaterial),
                    "slot " + slot + " keeps exact material identity");
                True(ReferenceEquals(
                        expectedPage,
                        renderer.Block["_TeamMask"]),
                    "slot " + slot + " receives page mask at chopFeet="
                    + chopFeet[slot]);
                True(ReferenceEquals(
                        foreignVector,
                        renderer.Block["_ForeignVector"]),
                    "slot " + slot + " preserves foreign MPB field");
                Equal("team-" + slot, renderer.Colour,
                    "slot " + slot + " preserves dynamic team colour");
                Equal(0.25f + slot * 0.1f, renderer.Alpha,
                    "slot " + slot + " preserves alpha");
                Equal(0.03125f + slot, material.SpriteCutoff,
                    "slot " + slot + " preserves extender cutoff");
            }

            var firstForeignMask = new object();
            var foreignMaterial = new HarnessMaskMaterial(
                true,
                firstForeignMask,
                0.8125f);
            var transition = new HarnessMaskRenderer(501, foreignMaterial)
            {
                Colour = "dynamic-team",
                Alpha = 0.375f
            };
            var foreignField = new object();
            transition.Block.Add("_ForeignFloat", foreignField);
            HarnessApplyPageMask(
                ownership, ownedMasks, transition, true, pageOne);
            HarnessApplyPageMask(
                ownership, ownedMasks, transition, false, null);
            True(ReferenceEquals(
                    firstForeignMask,
                    transition.Block["_TeamMask"]),
                "owned to foreign restores current foreign mask");
            True(ReferenceEquals(foreignMaterial, transition.SharedMaterial),
                "owned to foreign keeps material identity");
            True(ReferenceEquals(
                    foreignField,
                    transition.Block["_ForeignFloat"]),
                "owned to foreign keeps unrelated MPB field");
            Equal("dynamic-team", transition.Colour,
                "foreign transition preserves team colour");
            Equal(0.375f, transition.Alpha,
                "foreign transition preserves alpha");
            Equal(0.8125f, foreignMaterial.SpriteCutoff,
                "foreign transition preserves cutoff");

            var laterForeignMask = new object();
            foreignMaterial.Mask = laterForeignMask;
            HarnessApplyPageMask(
                ownership, ownedMasks, transition, false, null);
            True(ReferenceEquals(
                    laterForeignMask,
                    transition.Block["_TeamMask"]),
                "later source material mutation is not frozen");

            var foreignOverride = new object();
            transition.Block["_TeamMask"] = foreignOverride;
            foreignMaterial.Mask = new object();
            HarnessApplyPageMask(
                ownership, ownedMasks, transition, false, null);
            True(ReferenceEquals(
                    foreignOverride,
                    transition.Block["_TeamMask"]),
                "foreign MPB takeover is preserved");

            var materialOwnedField = new object();
            var materialOwnedTransition = new HarnessMaskRenderer(
                504,
                new HarnessMaskMaterial(true, new object(), 0.4375f));
            materialOwnedTransition.Block.Add(
                "_ForeignOwnedMaterialField",
                materialOwnedField);
            HarnessApplyPageMask(
                ownership,
                ownedMasks,
                materialOwnedTransition,
                true,
                pageZero);
            var otherOwnedPageMaterial = new HarnessMaskMaterial(
                true,
                pageOne,
                0.6875f);
            materialOwnedTransition.SharedMaterial = otherOwnedPageMaterial;
            bool materialOwnedReleaseBlocked = HarnessApplyPageMask(
                ownership,
                ownedMasks,
                materialOwnedTransition,
                false,
                null);
            True(materialOwnedReleaseBlocked,
                "owned page B in current material blocks native release");
            object materialOwnedTracked = HarnessTrackedMask(
                ownership,
                materialOwnedTransition);
            True(ReferenceEquals(
                    HarnessNeutralMask,
                    materialOwnedTransition.Block["_TeamMask"]),
                "owned page B in current material neutralizes page A MPB");
            True(!ReferenceEquals(pageZero, materialOwnedTracked)
                    && !ReferenceEquals(pageOne, materialOwnedTracked),
                "material cross-owned release tracks neither page A nor page B");
            True(ReferenceEquals(
                    otherOwnedPageMaterial,
                    materialOwnedTransition.SharedMaterial),
                "material cross-owned release preserves material identity");
            True(ReferenceEquals(
                    materialOwnedField,
                    materialOwnedTransition.Block["_ForeignOwnedMaterialField"]),
                "material cross-owned release preserves foreign MPB fields");

            var materialThenForeignMask = new object();
            var materialThenForeign = new HarnessMaskMaterial(
                true,
                materialThenForeignMask,
                0.9375f);
            materialOwnedTransition.SharedMaterial = materialThenForeign;
            HarnessApplyPageMask(
                ownership,
                ownedMasks,
                materialOwnedTransition,
                false,
                null);
            True(ReferenceEquals(
                    materialThenForeignMask,
                    materialOwnedTransition.Block["_TeamMask"]),
                "genuine foreign material mask survives cross-owned release");
            True(ReferenceEquals(
                    materialThenForeignMask,
                    HarnessTrackedMask(ownership, materialOwnedTransition)),
                "tracker records genuine foreign material after neutralization");

            var crossGroupOwnership =
                new AssetStreamPageMaskOwnership<object>();
            var bodyPageA = new object();
            var nonBodyGroupMaskB = new object();
            var crossGroupMasks = new AssetStreamReferenceCountSet<object>();
            crossGroupMasks.Add(bodyPageA);
            crossGroupMasks.Add(nonBodyGroupMaskB);
            var crossGroupField = new object();
            var crossGroupRenderer = new HarnessMaskRenderer(
                507,
                new HarnessMaskMaterial(true, new object(), 0.46875f));
            crossGroupRenderer.Block.Add(
                "_ForeignCrossGroupField",
                crossGroupField);
            HarnessApplyPageMask(
                crossGroupOwnership,
                crossGroupMasks,
                crossGroupRenderer,
                true,
                bodyPageA);
            var nonBodyOwnedMaterial = new HarnessMaskMaterial(
                true,
                nonBodyGroupMaskB,
                0.71875f);
            crossGroupRenderer.SharedMaterial = nonBodyOwnedMaterial;
            bool crossGroupTransitionBlocked = HarnessApplyPageMask(
                crossGroupOwnership,
                crossGroupMasks,
                crossGroupRenderer,
                true,
                nonBodyGroupMaskB,
                true);
            object crossGroupTracked = HarnessTrackedMask(
                crossGroupOwnership,
                crossGroupRenderer);
            True(!crossGroupTransitionBlocked,
                "multi-page to single-page masked transition stays active");
            True(ReferenceEquals(
                    nonBodyGroupMaskB,
                    crossGroupRenderer.Block["_TeamMask"]),
                "single-page masked group receives its exact mask, never neutral");
            True(ReferenceEquals(nonBodyGroupMaskB, crossGroupTracked),
                "cross-group tracker advances from page A to single-page mask B");
            True(ReferenceEquals(
                    nonBodyOwnedMaterial,
                    crossGroupRenderer.SharedMaterial),
                "masked cross-group transition preserves material identity");
            Equal(0.71875f, nonBodyOwnedMaterial.SpriteCutoff,
                "masked cross-group transition preserves cutoff");
            True(ReferenceEquals(
                    crossGroupField,
                    crossGroupRenderer.Block["_ForeignCrossGroupField"]),
                "masked cross-group transition preserves unrelated MPB fields");

            // Detaching routes during controlled unload is the point at which
            // the exact same renderer is neutralized. The material is one of
            // our page clones and is destroyed in this release, so it cannot
            // circularly block its own mask cleanup.
            bool laneOwnedReleaseBlocked = HarnessApplyPageMask(
                crossGroupOwnership,
                crossGroupMasks,
                crossGroupRenderer,
                false,
                null,
                true);
            True(!laneOwnedReleaseBlocked,
                "our own page material does not block its own release");
            True(ReferenceEquals(
                    HarnessNeutralMask,
                    crossGroupRenderer.Block["_TeamMask"]),
                "controlled detach removes the single-page owned mask");
            crossGroupTracked = HarnessTrackedMask(
                crossGroupOwnership,
                crossGroupRenderer);
            True(!ReferenceEquals(bodyPageA, crossGroupTracked)
                    && !ReferenceEquals(nonBodyGroupMaskB, crossGroupTracked),
                "controlled detach tracker retains neither owned mask");
            True(ReferenceEquals(
                    nonBodyOwnedMaterial,
                    crossGroupRenderer.SharedMaterial),
                "cross-group cleanup preserves shared material identity");
            True(ReferenceEquals(
                    crossGroupField,
                    crossGroupRenderer.Block["_ForeignCrossGroupField"]),
                "cross-group cleanup preserves unrelated MPB fields");
            True(HarnessApplyPageMask(
                    crossGroupOwnership,
                    crossGroupMasks,
                    crossGroupRenderer,
                    false,
                    null),
                "cross-group release stays blocked while owned material remains");

            crossGroupRenderer.SharedMaterial = new HarnessMaskMaterial(
                false,
                null,
                0.71875f);
            bool crossGroupResolved = HarnessApplyPageMask(
                crossGroupOwnership,
                crossGroupMasks,
                crossGroupRenderer,
                false,
                null);
            True(!crossGroupResolved,
                "plain material resolves cross-group release blocker");
            True(crossGroupMasks.Contains(bodyPageA)
                    && crossGroupMasks.Contains(nonBodyGroupMaskB),
                "central detach retains both masks for final release audit");
            True(ReferenceEquals(
                    HarnessNeutralMask,
                    crossGroupRenderer.Block["_TeamMask"]),
                "cross-group detach leaves no owned MPB reference");
            True(crossGroupMasks.Remove(bodyPageA)
                    && crossGroupMasks.Remove(nonBodyGroupMaskB),
                "native cleanup unregisters both masks after final audit");
            True(!crossGroupMasks.Contains(bodyPageA)
                    && !crossGroupMasks.Contains(nonBodyGroupMaskB),
                "no group-owned mask remains registered after cleanup");

            var postDetachForeignMask = new object();
            crossGroupRenderer.SharedMaterial = new HarnessMaskMaterial(
                true,
                postDetachForeignMask,
                0.78125f);
            HarnessApplyPageMask(
                crossGroupOwnership,
                crossGroupMasks,
                crossGroupRenderer,
                false,
                null);
            True(ReferenceEquals(
                    postDetachForeignMask,
                    crossGroupRenderer.Block["_TeamMask"]),
                "genuine foreign mask survives cross-group detach");

            var blockOwnedField = new object();
            var blockOwnedTransition = new HarnessMaskRenderer(
                505,
                new HarnessMaskMaterial(false, null, 0.5625f));
            blockOwnedTransition.Block.Add(
                "_ForeignOwnedBlockField",
                blockOwnedField);
            HarnessApplyPageMask(
                ownership,
                ownedMasks,
                blockOwnedTransition,
                true,
                pageZero);
            blockOwnedTransition.Block["_TeamMask"] = pageOne;
            HarnessApplyPageMask(
                ownership,
                ownedMasks,
                blockOwnedTransition,
                false,
                null);
            object blockOwnedTracked = HarnessTrackedMask(
                ownership,
                blockOwnedTransition);
            True(ReferenceEquals(
                    HarnessNeutralMask,
                    blockOwnedTransition.Block["_TeamMask"]),
                "direct MPB override to owned page B is neutralized");
            True(!ReferenceEquals(pageZero, blockOwnedTracked)
                    && !ReferenceEquals(pageOne, blockOwnedTracked),
                "MPB cross-owned release tracks neither page A nor page B");
            True(ReferenceEquals(
                    blockOwnedField,
                    blockOwnedTransition.Block["_ForeignOwnedBlockField"]),
                "MPB cross-owned release preserves foreign MPB fields");

            var blockThenForeignMask = new object();
            blockOwnedTransition.SharedMaterial = new HarnessMaskMaterial(
                true,
                blockThenForeignMask,
                0.96875f);
            HarnessApplyPageMask(
                ownership,
                ownedMasks,
                blockOwnedTransition,
                false,
                null);
            True(ReferenceEquals(
                    blockThenForeignMask,
                    blockOwnedTransition.Block["_TeamMask"]),
                "genuine foreign mask survives direct cross-owned cleanup");

            var conflictForeignMask = new object();
            var conflictField = new object();
            var conflictingOwners = new HarnessMaskRenderer(
                506,
                new HarnessMaskMaterial(true, new object(), 0.34375f));
            conflictingOwners.Block.Add("_ForeignConflictField", conflictField);
            HarnessApplyPageMask(
                ownership,
                ownedMasks,
                conflictingOwners,
                true,
                pageZero);
            conflictingOwners.Block["_TeamMask"] = conflictForeignMask;
            var conflictingOwnedMaterial = new HarnessMaskMaterial(
                true,
                pageOne,
                0.84375f);
            conflictingOwners.SharedMaterial = conflictingOwnedMaterial;
            bool conflictingReleaseBlocked = HarnessApplyPageMask(
                ownership,
                ownedMasks,
                conflictingOwners,
                false,
                null);
            True(conflictingReleaseBlocked,
                "foreign MPB plus owned material blocks release fail-closed");
            True(ReferenceEquals(
                    conflictForeignMask,
                    conflictingOwners.Block["_TeamMask"]),
                "release conflict never overwrites genuine foreign MPB mask");
            True(ownership.IsTracked(506, conflictingOwners),
                "release conflict retains ownership tracking");
            True(ReferenceEquals(
                    conflictField,
                    conflictingOwners.Block["_ForeignConflictField"]),
                "release conflict preserves unrelated foreign MPB field");

            var resolvedForeignMaterialMask = new object();
            conflictingOwners.SharedMaterial = new HarnessMaskMaterial(
                true,
                resolvedForeignMaterialMask,
                0.84375f);
            bool resolvedReleaseBlocked = HarnessApplyPageMask(
                ownership,
                ownedMasks,
                conflictingOwners,
                false,
                null);
            True(!resolvedReleaseBlocked,
                "genuine foreign material resolves owned release conflict");
            True(!ownership.IsTracked(506, conflictingOwners),
                "resolved foreign MPB takeover retires route tracking");
            True(ReferenceEquals(
                    conflictForeignMask,
                    conflictingOwners.Block["_TeamMask"]),
                "resolved conflict keeps genuine foreign MPB precedence");

            var plainTransition = new HarnessMaskRenderer(
                502,
                new HarnessMaskMaterial(true, new object(), 0.25f));
            var plainForeignField = new object();
            plainTransition.Block.Add("_ForeignColour", plainForeignField);
            HarnessApplyPageMask(
                ownership, ownedMasks, plainTransition, true, pageZero);
            var plain = new HarnessMaskMaterial(false, null, 0.625f);
            plainTransition.SharedMaterial = plain;
            HarnessApplyPageMask(
                ownership, ownedMasks, plainTransition, false, null);
            True(ReferenceEquals(plain, plainTransition.SharedMaterial),
                "owned to plain keeps exact plain material");
            True(ReferenceEquals(
                    HarnessNeutralMask,
                    plainTransition.Block["_TeamMask"]),
                "owned to plain releases the owned page texture");
            True(ReferenceEquals(
                    plainForeignField,
                    plainTransition.Block["_ForeignColour"]),
                "owned to plain keeps unrelated MPB field");
            Equal(0.625f, plain.SpriteCutoff,
                "owned to plain keeps material properties");

            var nextForeignMask = new object();
            var nextForeign = new HarnessMaskMaterial(
                true,
                nextForeignMask,
                0.75f);
            plainTransition.SharedMaterial = nextForeign;
            HarnessApplyPageMask(
                ownership, ownedMasks, plainTransition, false, null);
            True(ReferenceEquals(
                    nextForeignMask,
                    plainTransition.Block["_TeamMask"]),
                "plain transition remains tracked until mask-capable material");

            var unloadField = new object();
            var unload = new HarnessMaskRenderer(
                503,
                new HarnessMaskMaterial(true, new object(), 0.5f));
            unload.Block.Add("_ForeignUnloadField", unloadField);
            HarnessApplyPageMask(
                ownership, ownedMasks, unload, true, pageOne);
            unload.SharedMaterial = new HarnessMaskMaterial(false, null, 0.5f);
            IList<AssetStreamTrackedPageMask<object>> releaseRoutes =
                ownership.SnapshotTracked();
            for (int index = 0; index < releaseRoutes.Count; index++)
            {
                if (ReferenceEquals(releaseRoutes[index].Renderer, unload))
                {
                    HarnessApplyPageMask(
                        ownership, ownedMasks, unload, false, null);
                }
            }
            True(ReferenceEquals(
                    HarnessNeutralMask,
                    unload.Block["_TeamMask"]),
                "map unload leaves no owned texture reference in MPB");
            True(ReferenceEquals(
                    unloadField,
                    unload.Block["_ForeignUnloadField"]),
                "map unload preserves every foreign MPB field");
            True(!ReferenceEquals(pageOne, unload.Block["_TeamMask"]),
                "released page mask is not retained by surviving renderer");

            var reusedMask = new object();
            var reusedMaterial = new HarnessMaskMaterial(
                true,
                reusedMask,
                0.875f);
            unload.SharedMaterial = reusedMaterial;
            HarnessApplyPageMask(
                ownership, ownedMasks, unload, false, null);
            True(ReferenceEquals(reusedMask, unload.Block["_TeamMask"]),
                "post-unload foreign team material replaces neutral mask");
            True(ReferenceEquals(reusedMaterial, unload.SharedMaterial),
                "post-unload reuse keeps foreign material identity");
        }

        private static void TestCentralMaterialMaskAudit()
        {
            var ownerA = new AssetStreamOwnershipToken("BodyA", 9, 1);
            var ownerB = new AssetStreamOwnershipToken("FoliageB", 9, 2);
            var maskA = new HarnessEqualMask();
            var maskB = new HarnessEqualMask();
            var registrations = new Dictionary<
                AssetStreamOwnershipToken,
                object[]>();
            registrations.Add(ownerA, new object[] { maskA });
            registrations.Add(ownerB, new object[] { maskB });
            var liveMasks = new AssetStreamReferenceCountSet<object>();
            liveMasks.Add(maskA);
            liveMasks.Add(maskB);
            Action<object, ISet<AssetStreamOwnershipToken>> markOwners =
                delegate(object mask, ISet<AssetStreamOwnershipToken> owners)
                {
                    foreach (KeyValuePair<
                        AssetStreamOwnershipToken,
                        object[]> pair in registrations)
                    {
                        for (int index = 0;
                            index < pair.Value.Length;
                            index++)
                        {
                            if (ReferenceEquals(mask, pair.Value[index]))
                            {
                                owners.Add(pair.Key);
                                break;
                            }
                        }
                    }
                };
            Func<HarnessMaskMaterial, object> readMask =
                delegate(HarnessMaskMaterial material)
                {
                    return material.HasMask ? material.Mask : null;
                };

            var genuineForeign = new HarnessEqualMask();
            var preservedBaselineMaterial = new HarnessMaskMaterial(
                true,
                genuineForeign,
                0.28125f);
            var preservedBaselineArray = new[] { preservedBaselineMaterial };
            var foreignReplacementMaterial = new HarnessMaskMaterial(
                true,
                maskB,
                0.78125f);
            var foreignReplacementArray = new[] { foreignReplacementMaterial };
            HarnessMaskMaterial[][] central =
            {
                preservedBaselineArray,
                foreignReplacementArray
            };
            HarnessMaskMaterial[][] centralIdentity = central;

            var unsafeOwners = new HashSet<AssetStreamOwnershipToken>();
            AssetStreamCentralMaterialMaskAudit.MarkOwners(
                central,
                readMask,
                markOwners,
                unsafeOwners);
            True(unsafeOwners.Contains(ownerB),
                "foreign replacement array retaining owned mask B blocks B");
            True(!unsafeOwners.Contains(ownerA),
                "cross-owner central audit blocks the exact mask owner only");
            True(ReferenceEquals(centralIdentity, central)
                    && ReferenceEquals(
                        foreignReplacementArray,
                        central[1])
                    && ReferenceEquals(
                        foreignReplacementMaterial,
                        central[1][0]),
                "central audit never replaces foreign arrays or materials");
            True(ReferenceEquals(maskB, foreignReplacementMaterial.Mask)
                    && foreignReplacementMaterial.SpriteCutoff == 0.78125f,
                "central audit never mutates foreign material properties");
            True(registrations.ContainsKey(ownerB)
                    && liveMasks.Contains(maskB),
                "route detach retains mask B identity through release audit");

            foreignReplacementMaterial.Mask = genuineForeign;
            unsafeOwners.Clear();
            AssetStreamCentralMaterialMaskAudit.MarkOwners(
                central,
                readMask,
                markOwners,
                unsafeOwners);
            True(!unsafeOwners.Contains(ownerB),
                "genuine foreign replacement mask permits owner B release");

            preservedBaselineMaterial.Mask = maskB;
            unsafeOwners.Clear();
            AssetStreamCentralMaterialMaskAudit.MarkOwners(
                new[] { preservedBaselineArray },
                readMask,
                markOwners,
                unsafeOwners);
            True(unsafeOwners.Contains(ownerB),
                "preserved baseline material mutated to owned B blocks release");
            True(ReferenceEquals(
                    preservedBaselineMaterial,
                    preservedBaselineArray[0]),
                "mutated baseline material identity remains foreign-owned");

            preservedBaselineMaterial.Mask = null;
            unsafeOwners.Clear();
            AssetStreamCentralMaterialMaskAudit.MarkOwners(
                new[] { preservedBaselineArray },
                readMask,
                markOwners,
                unsafeOwners);
            True(!unsafeOwners.Contains(ownerB),
                "plain baseline material permits owner B release");
            True(registrations.Remove(ownerB) && liveMasks.Remove(maskB),
                "safe release unregisters mask B only after final audit");
            True(!liveMasks.Contains(maskB),
                "released owner B leaves no registered mask identity");

            unsafeOwners.Clear();
            AssetStreamCentralMaterialMaskAudit.MarkOwners(
                new[] { foreignReplacementArray },
                readMask,
                markOwners,
                unsafeOwners);
            Equal(0, unsafeOwners.Count,
                "foreign material stays unblocked after owner B unregister");
        }

        private static bool HarnessApplyPageMask(
            AssetStreamPageMaskOwnership<object> ownership,
            AssetStreamReferenceCountSet<object> ownedMasks,
            HarnessMaskRenderer renderer,
            bool owned,
            object ownedMask)
        {
            return HarnessApplyPageMask(
                ownership, ownedMasks, renderer, owned, ownedMask, false);
        }

        /// <summary>
        /// <paramref name="materialIsLaneOwned"/> marks the renderer's material
        /// as one of our own page clones rather than foreign state.
        /// </summary>
        private static bool HarnessApplyPageMask(
            AssetStreamPageMaskOwnership<object> ownership,
            AssetStreamReferenceCountSet<object> ownedMasks,
            HarnessMaskRenderer renderer,
            bool owned,
            object ownedMask,
            bool materialIsLaneOwned)
        {
            object blockMask;
            bool blockHasMask =
                renderer.Block.TryGetValue("_TeamMask", out blockMask);
            HarnessMaskMaterial material = renderer.SharedMaterial;
            bool blockMaskOwned = blockHasMask
                && ownedMasks.Contains(blockMask);
            bool materialMaskOwned = material.HasMask
                && ownedMasks.Contains(material.Mask);
            AssetStreamPageMaskDecision<object> decision = ownership.Route(
                renderer.InstanceId,
                renderer,
                owned,
                ownedMask,
                blockHasMask,
                blockMask,
                blockMaskOwned,
                material.HasMask,
                material.Mask,
                materialMaskOwned,
                materialIsLaneOwned,
                HarnessNeutralMask);
            if (decision.Write)
            {
                renderer.Block["_TeamMask"] = decision.Texture;
                ownership.RecordWriteSucceeded(
                    renderer.InstanceId,
                    renderer,
                    decision.Texture,
                    owned);
            }
            return decision.ReleaseBlocked;
        }

        private static object HarnessTrackedMask(
            AssetStreamPageMaskOwnership<object> ownership,
            HarnessMaskRenderer renderer)
        {
            IList<AssetStreamTrackedPageMask<object>> tracked =
                ownership.SnapshotTracked();
            for (int index = 0; index < tracked.Count; index++)
            {
                if (ReferenceEquals(tracked[index].Renderer, renderer))
                {
                    return tracked[index].LastWritten;
                }
            }
            throw new InvalidOperationException(
                "Expected page-mask renderer to remain tracked");
        }

        private static void TestOffMainEpochQueue()
        {
            var queue = new AssetStreamOffMainRequestQueue(4);
            queue.OpenEpoch(7);
            const int workerCount = 16;
            int admitted = 0;
            Exception failure = null;
            using (var start = new ManualResetEventSlim(false))
            {
                var workers = new Thread[workerCount];
                for (int index = 0; index < workers.Length; index++)
                {
                    workers[index] = new Thread(delegate()
                    {
                        try
                        {
                            start.Wait();
                            if (queue.TryEnqueue(2, 7))
                            {
                                Interlocked.Increment(ref admitted);
                            }
                        }
                        catch (Exception exception)
                        {
                            Interlocked.CompareExchange(
                                ref failure,
                                exception,
                                null);
                        }
                    });
                    workers[index].IsBackground = true;
                    workers[index].Start();
                }
                start.Set();
                for (int index = 0; index < workers.Length; index++)
                {
                    True(workers[index].Join(2000),
                        "CAS worker returned without blocking");
                }
            }
            if (failure != null)
            {
                throw new InvalidOperationException(
                    "off-main CAS worker failed",
                    failure);
            }
            Equal(1, admitted, "same GM/epoch admitted exactly once");
            Equal(1, queue.ApproximateCount, "one deduplicated request queued");
            IList<int> ending = queue.CloseEpochAndDrain(7);
            Equal(1, ending.Count, "ending epoch drains deduplicated request");
            Equal(2, ending[0], "ending epoch retains queued GM");

            // A newer epoch wins monotonically even if the old getter reaches
            // its CAS after the replacement map has already queued the GM.
            queue.OpenEpoch(8);
            True(queue.TryEnqueue(1, 8), "new epoch queued");
            True(!queue.TryEnqueue(1, 7), "delayed stale epoch rejected");
            True(!queue.TryEnqueue(1, 8), "new epoch remains deduplicated");
            int gm;
            True(queue.TryDequeue(8, out gm), "active epoch dequeued");
            Equal(1, gm, "stale entries discarded before active request");
            True(!queue.TryDequeue(8, out gm),
                "prior-epoch request cannot leak into active epoch");
        }

        private static void TestOffMainQueueDoesNotWaitForTimeline()
        {
            var queue = new AssetStreamOffMainRequestQueue(4);
            queue.OpenEpoch(9);
            var timeline = new AssetStreamMainThreadTimeline();
            using (var timelineEntered = new ManualResetEventSlim(false))
            using (var releaseTimeline = new ManualResetEventSlim(false))
            {
                var holder = new Thread(delegate()
                {
                    timeline.Execute(delegate()
                    {
                        timelineEntered.Set();
                        releaseTimeline.Wait();
                    });
                });
                holder.IsBackground = true;
                holder.Start();
                True(timelineEntered.Wait(TimeSpan.FromSeconds(2)),
                    "synthetic Unity/main-thread load holds timeline");

                bool queued = false;
                Exception failure = null;
                var elapsed = Stopwatch.StartNew();
                var getter = new Thread(delegate()
                {
                    try
                    {
                        // This is the complete production handoff after the
                        // frozen baseline array/dictionary lookup: one epoch CAS
                        // and one bounded concurrent enqueue.
                        queued = queue.TryEnqueue(3, 9);
                    }
                    catch (Exception exception)
                    {
                        failure = exception;
                    }
                });
                getter.IsBackground = true;
                getter.Start();
                True(getter.Join(500),
                    "worker getter handoff returns while timeline is held");
                elapsed.Stop();
                True(elapsed.ElapsedMilliseconds < 500,
                    "worker handoff stays within the nonblocking deadline");
                True(failure == null, "worker handoff does not throw");
                True(queued, "worker request queued exactly once");
                True(!timeline.TryExecute(delegate { }),
                    "main timeline remained held throughout worker return");

                releaseTimeline.Set();
                True(holder.Join(2000), "timeline holder released");
            }
            int gm;
            True(queue.TryDequeue(9, out gm), "main thread drains worker request");
            Equal(3, gm, "drained worker GM");
        }

        private static void TestCanonicalDocuments()
        {
            Fixture fixture = Fixture.Create();
            AssetStreamManifest index = AssetStreamManifestParser.ParseIndex(fixture.IndexRaw);
            Equal(AssetStreamContract.IndexSchema, index.Schema, "index schema");
            Equal(AssetStreamContract.BuildTarget, index.BuildTarget, "build target");
            Equal(1, index.Groups.Count, "group count");
            AssetStreamGroupManifest group = index.Groups[0];
            Equal("Runtime/AssetBundles/win64/sede.gm.animals.v2", group.BundlePath, "bundle path");
            Equal(64 * Mib, group.ResidentChargeBytes, "resident charge");
            Equal(448 * Mib, group.PredictedLoadPeakBytes, "manifest predicted load peak");
            Equal(448 * Mib, group.RecalculatePeakAdmissionBytes(), "peak charge");

            AssetStreamAtlasManifest atlas = AssetStreamManifestParser.ParseAtlasV2(
                fixture.AtlasRaw, group);
            Equal(1, atlas.Pages.Count, "page count");
            Equal(1, atlas.Frames.Count, "frame count");
            Equal(0, atlas.Frames[0].Page, "Sprite.Create page");
            Equal(256, atlas.Pages[0].Width, "POT page width");
            True(atlas.Pages[0].Mask != null, "required mask page");
            Equal(group.NamesSha256, fixture.NamesSha, "names binding");
        }

        private static void TestVanillaOmissions()
        {
            Fixture fixture = Fixture.Create();
            string sha = new string('d', 64);
            string omitted =
                "{\"array_size\":1,\"frame_count\":1,\"frames_sha256\":\""
                + sha + "\",\"gm_id\":8,\"group\":\"Trees\","
                + "\"names_sha256\":\"" + sha + "\","
                + "\"reason\":\"v1_frame_dimension_exceeded\"}";
            string source = Utf8.GetString(fixture.IndexRaw);
            byte[] raw = Utf8.GetBytes(source.Replace(
                "\"vanilla_omitted_groups\":[]",
                "\"vanilla_omitted_groups\":[" + omitted + "]"));
            AssetStreamManifest manifest = AssetStreamManifestParser.ParseIndex(raw);
            Equal(1, manifest.Groups.Count, "built group remains present");
            Equal(1, manifest.VanillaOmittedGroups.Count, "omission count");
            Equal("Trees", manifest.VanillaOmittedGroups[0].Group, "omitted group");

            Throws<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseIndex(Utf8.GetBytes(
                        Utf8.GetString(raw).Replace(
                            "v1_frame_dimension_exceeded",
                            "future_reason")));
                },
                "unknown omission reason");
            Throws<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseIndex(Utf8.GetBytes(
                        Utf8.GetString(raw).Replace(
                            "\"group\":\"Trees\"",
                            "\"group\":\"animals\"")));
                },
                "omitted/built group collision");
        }

        private static void TestMaterialBindingModes()
        {
            True(
                !AssetStreamMaterialBindingContract.RequiresExactSpriteMaskRoute(
                    AssetStreamMaskPolicy.Forbidden),
                "plain sprites never receive a page-mask route");
            True(
                AssetStreamMaterialBindingContract.RequiresExactSpriteMaskRoute(
                    AssetStreamMaskPolicy.Required),
                "every required-mask sprite receives an exact page-mask route");
            True(
                AssetStreamMaterialBindingContract.IsExact(
                    AssetStreamMaskPolicy.Forbidden,
                    "animals",
                    1,
                    AssetStreamMaterialBindingContract.PlainShared),
                "plain group mode");
            True(
                AssetStreamMaterialBindingContract.IsExact(
                    AssetStreamMaskPolicy.Required,
                    "animals",
                    1,
                    AssetStreamMaterialBindingContract.GroupMaskSinglePage),
                "single-page group mask mode");
            True(
                !AssetStreamMaterialBindingContract.IsExact(
                    AssetStreamMaskPolicy.Required,
                    "animals",
                    2,
                    AssetStreamMaterialBindingContract.GroupMaskSinglePage),
                "single-page group mask rejects page two");
            True(
                !AssetStreamMaterialBindingContract.IsExact(
                    AssetStreamMaskPolicy.Required,
                    "animals",
                    1,
                    AssetStreamMaterialBindingContract.SetBodySpritePageMask),
                "unreviewed group cannot use body route");
            True(
                AssetStreamMaterialBindingContract.IsExact(
                    AssetStreamMaskPolicy.Required,
                    "body_archer",
                    16,
                    AssetStreamMaterialBindingContract.SetBodySpritePageMask),
                "reviewed Body group supports multipage route");
        }

        private static void TestStrictGates()
        {
            Fixture fixture = Fixture.Create();
            byte[] noLf = new byte[fixture.IndexRaw.Length - 1];
            Buffer.BlockCopy(fixture.IndexRaw, 0, noLf, 0, noLf.Length);
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(noLf); },
                "missing LF");

            string index = Utf8.GetString(fixture.IndexRaw);
            byte[] badPath = Utf8.GetBytes(index.Replace(
                "Runtime/AssetBundles/win64/sede.gm.animals.v2",
                "Runtime/AssetBundles/groups/sede.gm.animals.v2"));
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(badPath); },
                "non-win64 path");

            byte[] nonPot = Utf8.GetBytes(index.Replace("\"height\":256", "\"height\":300"));
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(nonPot); },
                "non-POT page");

            byte[] spaced = Utf8.GetBytes(index.Replace("\":4096", "\": 4096"));
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(spaced); },
                "non-canonical whitespace");

            byte[] negativeZero = Utf8.GetBytes(
                index.Replace("\"gm_id\":7", "\"gm_id\":-0"));
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(negativeZero); },
                "Python-canonical index integer");

            byte[] gmOutsideLoader = Utf8.GetBytes(
                index.Replace("\"gm_id\":7", "\"gm_id\":234"));
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(gmOutsideLoader); },
                "gm id outside 234-slot loader");

            byte[] missingPredictedPeak = Utf8.GetBytes(index.Replace(
                ",\"predicted_load_peak_bytes\":469762048",
                string.Empty));
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(missingPredictedPeak); },
                "missing predicted load peak");

            byte[] wrongPredictedPeak = Utf8.GetBytes(index.Replace(
                "\"predicted_load_peak_bytes\":469762048",
                "\"predicted_load_peak_bytes\":469762049"));
            ThrowsContaining<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseIndex(wrongPredictedPeak); },
                "predicted_load_peak_bytes",
                "wrong predicted load peak");

            byte[] unreviewedBodyRoute = Utf8.GetBytes(index.Replace(
                "group_mask_single_page_v1",
                "set_body_sprite_postfix_page_mask_v1"));
            Throws<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseIndex(unreviewedBodyRoute);
                },
                "unreviewed group body material route");

            string atlas = Utf8.GetString(fixture.AtlasRaw);
            byte[] noncanonicalNumber = Utf8.GetBytes(
                atlas.Replace("\"x\":0.5", "\"x\":0.50"));
            AssetStreamGroupManifest rebound = RebindAtlasHash(
                fixture,
                noncanonicalNumber);
            Throws<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseAtlasV2(
                        noncanonicalNumber,
                        rebound);
                },
                "Python-canonical atlas number");

            byte[] emptyName = Utf8.GetBytes(
                atlas.Replace("\"name\":\"animal-0\"", "\"name\":\"\""));
            rebound = RebindAtlasHash(fixture, emptyName);
            Throws<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseAtlasV2(emptyName, rebound); },
                "empty frame name");

            Fixture authoredFixture = Fixture.Create("100.0", "-99.0");
            AssetStreamAtlasManifest authoredAtlas =
                AssetStreamManifestParser.ParseAtlasV2(
                    authoredFixture.AtlasRaw,
                    AssetStreamManifestParser.ParseIndex(
                        authoredFixture.IndexRaw).Groups[0]);
            Equal(100.0, authoredAtlas.Frames[0].Pivot.X,
                "authored pivot x outside normalized rect");
            Equal(-99.0, authoredAtlas.Frames[0].Pivot.Y,
                "authored pivot y outside normalized rect");

            Fixture spacedFixture = Fixture.Create(
                "0.5",
                "0.0",
                "puff of smoke",
                "puff_of_smoke");
            AssetStreamManifest spacedIndex =
                AssetStreamManifestParser.ParseIndex(spacedFixture.IndexRaw);
            AssetStreamAtlasManifest spacedAtlas =
                AssetStreamManifestParser.ParseAtlasV2(
                    spacedFixture.AtlasRaw,
                    spacedIndex.Groups[0]);
            Equal("puff of smoke", spacedAtlas.Group,
                "semantic group identity retains spaces");
            Equal("puff_of_smoke", spacedAtlas.Slug,
                "semantic group uses a separate safe slug");

            Fixture abusiveFixture = Fixture.Create("100.0001", "0.0");
            Throws<AssetStreamManifestParseException>(
                delegate
                {
                    AssetStreamManifestParser.ParseAtlasV2(
                        abusiveFixture.AtlasRaw,
                        AssetStreamManifestParser.ParseIndex(
                            abusiveFixture.IndexRaw).Groups[0]);
                },
                "pivot beyond the defensive bound");

            byte[] corrupt = (byte[])fixture.AtlasRaw.Clone();
            corrupt[0] = (byte)'[';
            AssetStreamGroupManifest original =
                AssetStreamManifestParser.ParseIndex(fixture.IndexRaw).Groups[0];
            ThrowsContaining<AssetStreamManifestParseException>(
                delegate { AssetStreamManifestParser.ParseAtlasV2(corrupt, original); },
                "hash mismatch",
                "atlas hash precedes parse");

            True(AssetStreamManifestParser.CompareFrameNamesForContract(
                    "\ue000",
                    char.ConvertFromUtf32(0x10000)) < 0,
                "Python Unicode-codepoint frame ordering");
        }

        private static void TestAccountingAndPolicy()
        {
            AssetStreamResourcePolicy policy =
                AssetStreamResourcePolicy.Windows24GbIgpuSafeV1();
            Equal("windows_24gb_igpu_safe_v1", policy.Kind, "policy id");
            Equal(3 * Gib, policy.AdditionalGmResidentBytes, "GM budget");
            Equal(1 * Gib, policy.UiResidentBytes, "UI budget");
            Equal(16 * Mib, policy.AudioStreamBytes, "audio budget");
            Equal(16 * Gib, policy.ProcessPrivateCeilingBytes, "private ceiling");
            Equal(8 * Gib, policy.GlobalCommitReserveBytes, "commit reserve");
            Equal(4 * Gib, policy.MinimumFreePhysicalBytes, "physical reserve");
            Equal(2 * Gib, policy.PeakAdmissionBytes, "peak cap");
            Equal(234, AssetStreamContract.MaximumGroups,
                "spriteLoader outer-array group cap");
            Equal(16, AssetStreamContract.MaximumPagesPerGroup,
                "tested page cap");
            Equal(4096, AssetStreamContract.MaximumFramesPerGroup,
                "tested frame cap");
            Equal(4 * Mib, AssetStreamContract.MaximumIndexBytes,
                "tested index byte cap");
            Equal(4 * Mib, AssetStreamContract.MaximumAtlasBytes,
                "tested atlas byte cap");
            Equal(64 * Mib, AssetStreamAccounting.CalculateResidentChargeBytes(8), "ceil 9/8");
            Equal(448 * Mib, AssetStreamAccounting.CalculatePeakAdmissionBytes(64 * Mib, 1), "exact peak");
            Throws<OverflowException>(
                delegate { AssetStreamAccounting.CalculateResidentChargeBytes(long.MaxValue); },
                "resident overflow");
        }

        private static void TestAdmission()
        {
            Fixture fixture = Fixture.Create();
            AssetStreamGroupManifest group =
                AssetStreamManifestParser.ParseIndex(fixture.IndexRaw).Groups[0];
            var memory = new HarnessMemoryProbe(GoodMemory(), GoodMemory());
            var usage = new HarnessUsageProbe(0, 0);
            var ledger = NewLedger(memory, usage);
            AssetStreamBudgetReservation reservation;
            AssetStreamAdmissionDecision decision;
            True(ledger.TryReserve(group, out reservation, out decision), "pre-admission");
            Equal("admitted", decision.ReasonToken, "authoritative admitted reason");
            True(reservation.TryConfirmBeforeCommit(out decision), "post-staging admission");
            Equal(2, memory.CaptureCount, "two memory probes");
            Equal(2, usage.CaptureCount, "two external usage probes");
            reservation.Commit();
            Equal(64 * Mib, ledger.Snapshot().CommittedGmResidentBytes, "committed charge");
            reservation.Release();

            var unavailable = NewLedger(
                new HarnessMemoryProbe(new AssetStreamMemorySnapshot(1 * Gib, 20 * Gib, null, "physical unavailable")),
                new HarnessUsageProbe(0, 0));
            True(!unavailable.TryReserve(group, out reservation, out decision), "missing metric denied");
            Equal(AssetStreamAdmissionFailure.MetricUnavailable, decision.Failure, "missing metric reason");
            Equal("metric_unavailable", decision.ReasonToken, "metric reason token");

            AssetStreamGroupManifest peakGroup = SyntheticGroup("Peak", 1 * Gib, 1);
            var peakMemory = new HarnessMemoryProbe(GoodMemory());
            var peakLedger = NewLedger(
                peakMemory,
                new HarnessUsageProbe(0, 0));
            True(!peakLedger.TryReserve(peakGroup, out reservation, out decision), "peak denied");
            Equal(AssetStreamAdmissionFailure.PeakBudgetExceeded, decision.Failure, "peak reason");
            Equal(0, peakMemory.CaptureCount, "peak cap precedes memory probe");
        }

        private static void TestSecondAdmissionDenial()
        {
            Fixture fixture = Fixture.Create();
            AssetStreamManifest manifest = AssetStreamManifestParser.ParseIndex(fixture.IndexRaw);

            var reasonMemory = new HarnessMemoryProbe(
                GoodMemory(),
                new AssetStreamMemorySnapshot(
                    1 * Gib,
                    20 * Gib,
                    4 * Gib,
                    "staging consumed headroom"));
            var reasonLedger = NewLedger(reasonMemory, new HarnessUsageProbe(0, 0));
            AssetStreamBudgetReservation reasonReservation;
            AssetStreamAdmissionDecision reasonDecision;
            True(reasonLedger.TryReserve(
                manifest.Groups[0],
                out reasonReservation,
                out reasonDecision), "reason pre-admission");
            True(!reasonReservation.TryConfirmBeforeCommit(out reasonDecision),
                "reason post-staging denial");
            Equal("minimum_free_physical", reasonDecision.ReasonToken,
                "authoritative second-admission reason");
            reasonReservation.Cancel();

            var memory = new HarnessMemoryProbe(
                GoodMemory(),
                new AssetStreamMemorySnapshot(1 * Gib, 20 * Gib, 4 * Gib, "staging consumed headroom"));
            var backend = new HarnessBackend(memory);
            var controller = NewController(manifest, backend, memory);
            controller.RegisterBaseline("Animals", new HarnessBaseline("vanilla"));
            controller.BeginMapEpoch();
            AssetStreamEnsureResult result = controller.EnsureGroup("Animals");
            Equal(AssetStreamEnsureDisposition.BudgetFallback, result.Disposition, "fallback result");
            Equal(1, backend.StageCount, "staged once");
            Equal(0, backend.CommitCount, "never published");
            Equal(1, backend.AbortCount, "staging aborted");
            Equal(2, memory.CaptureCount, "fresh post-staging probe");
            Equal(AssetStreamGroupState.BudgetDenied,
                controller.Snapshot("Animals").State, "terminal epoch fallback");
        }

        private static void TestControllerLifecycle()
        {
            Fixture fixture = Fixture.Create();
            AssetStreamManifest manifest = AssetStreamManifestParser.ParseIndex(fixture.IndexRaw);
            var memory = new HarnessMemoryProbe(GoodMemory(), GoodMemory());
            var backend = new HarnessBackend(memory);
            var controller = NewController(manifest, backend, memory);
            controller.RegisterBaseline("Animals", new HarnessBaseline("vanilla"));
            long epoch = controller.BeginMapEpoch();
            AssetStreamEnsureResult result = controller.EnsureGm(7);
            True(result.IsLoaded, "loaded");
            Equal(1, backend.StageCount, "staged");
            Equal(1, backend.CommitCount, "published once");
            Equal(2, backend.MemoryCapturesAtCommit, "publish follows second probe");
            controller.EndMapEpoch(epoch);
            Equal(1, backend.RestoreCount, "baseline restored");
            Equal(0, controller.AdvanceLateFrame(), "first full delay frame");
            Equal(1, controller.AdvanceLateFrame(), "second full delay frame releases");
            Equal(1, backend.ReleaseCount, "released exactly once");
            Equal(AssetStreamGroupState.Unloaded,
                controller.Snapshot("Animals").State, "unloaded state");
        }

        private static void TestGlobalUnloadBatch()
        {
            var coordinator = new AssetStreamGlobalUnloadBatch<object>();
            var participants = new object[234];
            for (int index = 0; index < participants.Length; index++)
            {
                participants[index] = new object();
                True(coordinator.Enqueue(participants[index]),
                    "enqueue release participant " + index.ToString(
                        CultureInfo.InvariantCulture));
            }
            True(!coordinator.Enqueue(participants[0]),
                "duplicate cleanup is not queued twice");

            int globalScanStarts = 0;
            IList<object> first;
            True(coordinator.TryBegin(out first), "release wave starts");
            globalScanStarts++;
            Equal(234, first.Count, "all groups share first scan");
            IList<object> none;
            True(!coordinator.TryBegin(out none),
                "no parallel global scan while first is active");
            Equal(234, coordinator.Complete().Count,
                "whole release wave completes together");
            Equal(1, globalScanStarts,
                "234 due groups invoke exactly one global scan");

            var later = new object();
            True(coordinator.Enqueue(later), "later wave queued");
            IList<object> second;
            True(coordinator.TryBegin(out second), "later wave starts separately");
            Equal(1, second.Count, "later wave membership");
            coordinator.AbortStart();
            Equal(1, coordinator.WaitingCount,
                "failed Unity start retains ownership for retry");
            True(coordinator.TryBegin(out second), "failed wave retries");
            Equal(1, coordinator.Complete().Count, "retried wave completes");
            True(!coordinator.HasPending, "coordinator drains completely");
        }

        private static void TestMapStartGate()
        {
            var gate = new AssetStreamMapStartGate();
            Fixture fixture = Fixture.Create();
            AssetStreamManifest manifest =
                AssetStreamManifestParser.ParseIndex(fixture.IndexRaw);
            var memory = new HarnessMemoryProbe(GoodMemory(), GoodMemory());
            var backend = new HarnessBackend(memory);
            var controller = NewController(manifest, backend, memory);
            controller.RegisterBaseline("Animals", new HarnessBaseline("vanilla"));
            Equal(AssetStreamMapGateAction.BeginEpoch,
                gate.OnMapLoadPre(true),
                "Load PRE begins the epoch before native map construction/getters");
            long epoch = controller.BeginMapEpoch();
            True(controller.EnsureGm(7).IsLoaded,
                "getter between Load PRE and POST publishes the streamed group");
            True(gate.IgnoreNestedUnload,
                "native load pair marks old-map unloads as nested");
            Equal(AssetStreamMapGateAction.None,
                gate.OnMapLoadPre(true),
                "duplicate Load PRE cannot begin another epoch");
            gate.OnMapLoadPost();
            True(gate.IgnoreNestedUnload,
                "inner Load POST cannot close the outer Load pair");
            gate.OnMapLoadPost();
            Equal(AssetStreamMapGateAction.None,
                gate.OnStartPre(true),
                "Start PRE deduplicates the epoch already opened by Load PRE");
            gate.OnStartPost();
            True(gate.EpochBegun,
                "Start POST preserves the active map epoch");
            Equal(AssetStreamMapGateAction.BeginEpoch,
                gate.OnSaveLoadPre(true),
                "top-level Save PRE rolls the active atlas epoch");
            controller.EndMapEpoch(epoch);
            long saveEpoch = controller.BeginMapEpoch();
            True(gate.IgnoreNestedUnload,
                "Save load owns and ignores its nested old-map unload callbacks");
            Equal(AssetStreamMapGateAction.None,
                gate.OnMapLoadPre(true),
                "nested map-file load shares the replacement Save epoch");
            AssetStreamEnsureResult releasePending = controller.EnsureGm(7);
            Equal(AssetStreamEnsureDisposition.ReleasePendingFallback,
                releasePending.Disposition,
                "replacement request waits for old ownership cleanup");
            gate.OnMapLoadPost();
            gate.OnSaveLoadPost();
            True(gate.EpochBegun && !gate.IgnoreNestedUnload,
                "replacement epoch survives the complete nested Save load");
            controller.AdvanceLateFrame();
            controller.AdvanceLateFrame();
            AssetStreamGroupSnapshot releasedSaveGroup =
                controller.Snapshot("Animals");
            Equal(AssetStreamGroupState.Unloaded,
                releasedSaveGroup.State,
                "old Save-load ownership is released after the full delay");
            True(releasedSaveGroup.Queued,
                "replacement request remains queued after old cleanup");
            controller.EndMapEpoch(saveEpoch);
            gate.OnExternalUnload();

            int saveEpochBegins = 0;
            if (gate.OnSaveLoadPre(true)
                == AssetStreamMapGateAction.BeginEpoch)
            {
                saveEpochBegins++;
            }
            True(gate.IgnoreNestedUnload,
                "LoadSave PRE owns its inner old-map unload notifications");
            Equal(AssetStreamMapGateAction.None,
                gate.OnSaveLoadPre(true),
                "nested same-kind Save PRE is depth-deduplicated");
            True(gate.IgnoreNestedUnload && gate.IgnoreNestedUnload,
                "multiple nested Unload PRE callbacks do not end the new epoch");
            gate.OnSaveLoadPost();
            True(gate.IgnoreNestedUnload,
                "inner Save POST cannot close the outer Save pair");
            gate.OnSaveLoadPost();
            Equal(1, saveEpochBegins,
                "LoadSave PRE through POST begins exactly one new epoch");
            True(gate.EpochBegun && !gate.IgnoreNestedUnload,
                "save-load POST leaves the new epoch active without StartMap");
            gate.OnExternalUnload();

            Equal(AssetStreamMapGateAction.EndOldToVanilla,
                gate.OnMapLoadPre(false),
                "Load PRE before baseline stays vanilla until capture is complete");
            Equal(AssetStreamMapGateAction.BeginEpoch,
                gate.OnBaselineCompleted(),
                "baseline postfix begins a waiting Load-PRE epoch immediately");
            Equal(AssetStreamMapGateAction.None,
                gate.OnBaselineCompleted(),
                "baseline completion cannot duplicate the epoch");
            gate.OnMapLoadPost();
            Equal(AssetStreamMapGateAction.None,
                gate.OnStartPre(true),
                "Start fallback deduplicates baseline-triggered load epoch");
            gate.OnStartPost();
            gate.OnExternalUnload();

            Equal(AssetStreamMapGateAction.EndOldToVanilla,
                gate.OnStartPre(false),
                "Start PRE fallback without baseline waits");
            gate.OnStartPost();
            Equal(AssetStreamMapGateAction.None,
                gate.OnBaselineCompleted(),
                "baseline arriving after Start POST stays fail-safe vanilla");
            gate.Reset();

            Equal(AssetStreamMapGateAction.None,
                gate.OnEditorReady(false),
                "editor before baseline remains vanilla");
            Equal(AssetStreamMapGateAction.BeginEpoch,
                gate.OnEditorReady(true),
                "ready editor begins its missing epoch after baseline");
            Equal(AssetStreamMapGateAction.None,
                gate.OnEditorReady(true),
                "ready editor begins exactly once");
            Equal(AssetStreamMapGateAction.None,
                gate.OnStartPre(true),
                "native Start after editor fallback is deduplicated");
            gate.OnStartPost();
            gate.OnExternalUnload();
        }

        private static void TestEpochRestoreOrdering()
        {
            Fixture fixture = Fixture.Create();
            AssetStreamManifest manifest =
                AssetStreamManifestParser.ParseIndex(fixture.IndexRaw);
            var memory = new HarnessMemoryProbe(GoodMemory(), GoodMemory());
            var backend = new HarnessBackend(memory);
            var order = new List<string>();
            backend.LifecycleOrder = order;
            RuntimeAssetStreamController<HarnessBaseline, HarnessCommitted>
                controller = NewController(manifest, backend, memory);
            controller.RegisterBaseline("Animals", new HarnessBaseline("vanilla"));
            long epoch = controller.BeginMapEpoch();

            AssetStreamEnsureResult result = controller.EnsureGm(7);
            Equal(AssetStreamEnsureDisposition.Loaded, result.Disposition,
                "group reaches a terminal loaded state");
            order.Add("group_loaded");
            controller.EndMapEpoch(epoch);
            order.Add("scene_reset");
            order.Add("summary");

            True(IsValidEpochCloseOrder(order),
                "restore completes before reset and summary");
            True(!IsValidEpochCloseOrder(new List<string>
                { "group_loaded", "scene_reset", "restore", "summary" }),
                "reset-before-restore ordering is rejected");
            True(!IsValidEpochCloseOrder(new List<string>
                { "group_loaded", "restore", "summary", "scene_reset" }),
                "summary-before-reset ordering is rejected");
        }

        private static bool IsValidEpochCloseOrder(IList<string> order)
        {
            int terminal = order.IndexOf("group_loaded");
            int restore = order.IndexOf("restore");
            int reset = order.IndexOf("scene_reset");
            int summary = order.IndexOf("summary");
            return terminal >= 0
                && restore > terminal
                && reset > restore
                && summary > reset;
        }

        private static RuntimeAssetStreamController<HarnessBaseline, HarnessCommitted>
            NewController(
                AssetStreamManifest manifest,
                HarnessBackend backend,
                HarnessMemoryProbe memory)
        {
            return new RuntimeAssetStreamController<HarnessBaseline, HarnessCommitted>(
                manifest,
                backend,
                new HarnessThreadGate(),
                NewLedger(memory, new HarnessUsageProbe(0, 0)),
                new AssetStreamControllerOptions(2),
                NullAssetStreamEventSink.Instance);
        }

        private static RuntimeAssetStreamController<HarnessBaseline, HarnessCommitted>
            NewController(
                AssetStreamManifest manifest,
                HarnessBackend backend,
                HarnessMemoryProbe memory,
                IAssetStreamThreadGate threadGate,
                IAssetStreamEventSink events)
        {
            return new RuntimeAssetStreamController<HarnessBaseline, HarnessCommitted>(
                manifest,
                backend,
                threadGate,
                NewLedger(memory, new HarnessUsageProbe(0, 0)),
                new AssetStreamControllerOptions(2),
                events);
        }

        private static AssetStreamBudgetLedger NewLedger(
            IAssetStreamMemoryProbe memory,
            IAssetStreamExternalUsageProbe usage)
        {
            return new AssetStreamBudgetLedger(
                AssetStreamResourcePolicy.Windows24GbIgpuSafeV1(), memory, usage);
        }

        private static AssetStreamMemorySnapshot GoodMemory()
        {
            return new AssetStreamMemorySnapshot(1 * Gib, 20 * Gib, 12 * Gib, string.Empty);
        }

        private static AssetStreamGroupManifest SyntheticGroup(
            string name, long rawBytes, long bundleBytes)
        {
            string slug = name.ToLowerInvariant();
            long charge = AssetStreamAccounting.CalculateResidentChargeBytes(rawBytes);
            long peak = AssetStreamAccounting.CalculatePeakAdmissionBytes(
                charge,
                bundleBytes);
            string sha = new string('a', 64);
            return new AssetStreamGroupManifest(
                name, slug, 100, false, 1,
                "sede.gm." + slug + ".v2",
                "Runtime/AssetBundles/win64/sede.gm." + slug + ".v2",
                bundleBytes, sha, "bbbbbbbb", new string('c', 32),
                "Assets/Generated/Groups/" + slug + "/atlas.v2.json",
                "sede/gm/" + slug + "/atlas.v2.json", sha,
                AssetStreamMaskPolicy.Forbidden, "plain_shared_v1", 1, 1,
                sha, sha, rawBytes, charge, peak,
                new List<AssetStreamIndexPageSummary>
                {
                    new AssetStreamIndexPageSummary(
                        0, 256, 256,
                        "sede/gm/" + slug + "/page/000/main", sha, null, null),
                });
        }

        private static void Run(string name, Action action)
        {
            try { action(); passed++; Console.WriteLine("PASS " + name); }
            catch (Exception exception)
            {
                Console.Error.WriteLine("FAIL " + name + ": " + exception);
                Environment.Exit(1);
            }
        }

        private static void True(bool value, string label)
        {
            if (!value) throw new InvalidOperationException(label + " was false");
        }

        private static void Equal<T>(T expected, T actual, string label)
        {
            if (!EqualityComparer<T>.Default.Equals(expected, actual))
                throw new InvalidOperationException(label + ": expected=" + expected + ", actual=" + actual);
        }

        private static void Throws<TException>(Action action, string label)
            where TException : Exception
        {
            try { action(); }
            catch (TException) { return; }
            throw new InvalidOperationException(label + " did not throw " + typeof(TException).Name);
        }

        private static void ThrowsContaining<TException>(
            Action action,
            string expectedText,
            string label)
            where TException : Exception
        {
            try
            {
                action();
            }
            catch (TException exception)
            {
                if (exception.Message.IndexOf(
                    expectedText,
                    StringComparison.OrdinalIgnoreCase) < 0)
                {
                    throw new InvalidOperationException(
                        label + " did not contain '" + expectedText + "': "
                        + exception.Message);
                }
                return;
            }
            throw new InvalidOperationException(
                label + " did not throw " + typeof(TException).Name);
        }

        private static AssetStreamGroupManifest RebindAtlasHash(
            Fixture fixture,
            byte[] atlasRaw)
        {
            string index = Utf8.GetString(fixture.IndexRaw);
            string previous = HashBytes(fixture.AtlasRaw);
            string replacement = HashBytes(atlasRaw);
            byte[] rebound = Utf8.GetBytes(index.Replace(previous, replacement));
            return AssetStreamManifestParser.ParseIndex(rebound).Groups[0];
        }

        private sealed class Fixture
        {
            private Fixture(byte[] indexRaw, byte[] atlasRaw, string namesSha)
            {
                IndexRaw = indexRaw;
                AtlasRaw = atlasRaw;
                NamesSha = namesSha;
            }

            internal byte[] IndexRaw { get; private set; }
            internal byte[] AtlasRaw { get; private set; }
            internal string NamesSha { get; private set; }

            internal static Fixture Create(
                string pivotX = "0.5",
                string pivotY = "0.0",
                string groupName = "Animals",
                string slug = "animals")
            {
                string sha = new string('a', 64);
                string frame =
                    "{\"alt\":false,\"index\":0,\"main_rgba_sha256\":\"" + sha
                    + "\",\"mask_rgba_sha256\":\"" + sha
                    + "\",\"name\":\"animal-0\",\"page\":0,"
                    + "\"pivot\":{\"x\":" + pivotX + ",\"y\":" + pivotY
                    + "},\"pixels_per_unit\":1.0,"
                    + "\"rect\":{\"height\":1,\"width\":1,\"x\":1,\"y\":1}}";
                string framesSha = HashText("[" + frame + "]");
                string namesSha = HashText("[\"animal-0\"]");
                string main =
                    "{\"address\":\"sede/gm/" + slug + "/page/000/main\","
                    + "\"asset_path\":\"Assets/Generated/Groups/" + slug
                    + "/page-000-main.png\","
                    + "\"png_sha256\":\"" + sha + "\",\"rgba_sha256\":\"" + sha + "\"}";
                string mask =
                    "{\"address\":\"sede/gm/" + slug + "/page/000/mask\","
                    + "\"asset_path\":\"Assets/Generated/Groups/" + slug
                    + "/page-000-mask.png\","
                    + "\"png_sha256\":\"" + sha + "\",\"rgba_sha256\":\"" + sha + "\"}";
                string atlas =
                    "{\"bundle\":\"sede.gm." + slug + ".v2\","
                    + "\"coordinate_system\":\"unity_bottom_left\","
                    + "\"frames\":[" + frame + "],\"frames_sha256\":\"" + framesSha + "\","
                    + "\"group\":\"" + groupName + "\",\"mask_policy\":\"required\","
                    + "\"material_binding\":\"group_mask_single_page_v1\","
                    + "\"max_page_dimension\":4096,\"padding_pixels\":1,"
                    + "\"pages\":[{\"height\":256,\"id\":0,\"main\":" + main
                    + ",\"mask\":" + mask + ",\"width\":256}],"
                    + "\"schema\":\"stronghold-europe-de.atlas.v2\",\"slug\":\""
                    + slug + "\","
                    + "\"texture_contract\":{\"alpha_is_transparency\":false,"
                    + "\"alpha_source\":\"FromInput\",\"filter_mode\":\"Point\","
                    + "\"format\":\"RGBA32\",\"mipmaps\":false,\"npot_scale\":\"None\","
                    + "\"readable\":false,\"s_rgb\":true,\"wrap_mode\":\"Clamp\"}}";
                byte[] atlasRaw = Utf8.GetBytes(atlas + "\n");
                string atlasSha = HashBytes(atlasRaw);
                string pageSummary =
                    "{\"height\":256,\"id\":0,\"main_address\":\"sede/gm/"
                    + slug + "/page/000/main\","
                    + "\"main_rgba_sha256\":\"" + sha
                    + "\",\"mask_address\":\"sede/gm/" + slug + "/page/000/mask\","
                    + "\"mask_rgba_sha256\":\"" + sha + "\",\"width\":256}";
                string group =
                    "{\"array_size\":1,\"atlas_address\":\"sede/gm/" + slug
                    + "/atlas.v2.json\","
                    + "\"atlas_asset_path\":\"Assets/Generated/Groups/" + slug
                    + "/atlas.v2.json\","
                    + "\"atlas_sha256\":\"" + atlasSha + "\",\"bundle\":\"sede.gm."
                    + slug + ".v2\","
                    + "\"bundle_crc32\":\"bbbbbbbb\","
                    + "\"bundle_path\":\"Runtime/AssetBundles/win64/sede.gm."
                    + slug + ".v2\","
                    + "\"bundle_sha256\":\"" + sha + "\",\"bundle_size_bytes\":1024,"
                    + "\"dash_format\":false,\"frame_count\":1,\"frames_sha256\":\"" + framesSha + "\","
                    + "\"gm_id\":7,\"group\":\"" + groupName
                    + "\",\"lifetime\":\"map\","
                    + "\"mask_policy\":\"required\","
                    + "\"material_binding\":\"group_mask_single_page_v1\","
                    + "\"names_sha256\":\"" + namesSha + "\",\"page_count\":1,"
                    + "\"pages\":[" + pageSummary + "],"
                    + "\"predicted_load_peak_bytes\":469762048,\"raw_rgba_bytes\":524288,"
                    + "\"resident_charge_bytes\":67108864,\"slug\":\"" + slug + "\","
                    + "\"unity_hash128\":\"" + new string('c', 32) + "\"}";
                string index =
                    "{\"build_id\":\"" + sha + "\",\"build_target\":\"StandaloneWindows64\","
                    + "\"groups\":[" + group + "],\"max_page_dimension\":4096,"
                    + "\"schema\":\"stronghold-europe-de.asset-bundle-index.v1\","
                    + "\"unity\":{\"revision\":\"88f88f591b2e\",\"version\":\"2021.3.45f2\"},"
                    + "\"vanilla_omitted_groups\":[]}";
                return new Fixture(Utf8.GetBytes(index + "\n"), atlasRaw, namesSha);
            }
        }

        private static string HashText(string value) { return HashBytes(Utf8.GetBytes(value)); }

        private static string HashBytes(byte[] value)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(value);
                var result = new StringBuilder(64);
                for (int index = 0; index < digest.Length; index++)
                    result.Append(digest[index].ToString("x2", CultureInfo.InvariantCulture));
                return result.ToString();
            }
        }

        private sealed class HarnessMaskMaterial
        {
            internal HarnessMaskMaterial(
                bool hasMask,
                object mask,
                float spriteCutoff)
            {
                HasMask = hasMask;
                Mask = mask;
                SpriteCutoff = spriteCutoff;
            }

            internal bool HasMask { get; private set; }
            internal object Mask { get; set; }
            internal float SpriteCutoff { get; private set; }
        }

        private sealed class HarnessEqualMask
        {
            public override bool Equals(object value)
            {
                return value is HarnessEqualMask;
            }

            public override int GetHashCode()
            {
                return 1;
            }
        }

        private sealed class HarnessMaskRenderer
        {
            internal HarnessMaskRenderer(
                int instanceId,
                HarnessMaskMaterial sharedMaterial)
            {
                InstanceId = instanceId;
                SharedMaterial = sharedMaterial;
                Block = new Dictionary<string, object>(StringComparer.Ordinal);
            }

            internal int InstanceId { get; private set; }
            internal HarnessMaskMaterial SharedMaterial { get; set; }
            internal Dictionary<string, object> Block { get; private set; }
            internal string Colour { get; set; }
            internal float Alpha { get; set; }
        }

        private sealed class HarnessBaseline
        {
            internal HarnessBaseline(string value) { Value = value; }
            internal string Value { get; private set; }
        }

        private sealed class HarnessCommitted
        {
            internal HarnessCommitted(string value) { Value = value; }
            internal string Value { get; private set; }
        }

        private sealed class HarnessThreadGate : IAssetStreamThreadGate
        {
            public bool IsMainThread { get { return true; } }
        }

        private sealed class CapturedHarnessThreadGate : IAssetStreamThreadGate
        {
            private readonly int mainThreadId;

            internal CapturedHarnessThreadGate(int mainThreadIdValue)
            {
                mainThreadId = mainThreadIdValue;
            }

            public bool IsMainThread
            {
                get
                {
                    return Thread.CurrentThread.ManagedThreadId == mainThreadId;
                }
            }
        }

        private sealed class HarnessEventSink : IAssetStreamEventSink
        {
            private readonly List<int> threadIds = new List<int>();

            internal int Count { get { return threadIds.Count; } }

            public void Emit(AssetStreamEvent value)
            {
                threadIds.Add(Thread.CurrentThread.ManagedThreadId);
            }

            internal bool AllOnThread(int expectedThreadId)
            {
                if (threadIds.Count == 0)
                {
                    return false;
                }
                for (int index = 0; index < threadIds.Count; index++)
                {
                    if (threadIds[index] != expectedThreadId)
                    {
                        return false;
                    }
                }
                return true;
            }
        }

        private sealed class HarnessMemoryProbe : IAssetStreamMemoryProbe
        {
            private readonly Queue<AssetStreamMemorySnapshot> values;
            private AssetStreamMemorySnapshot last;

            internal HarnessMemoryProbe(params AssetStreamMemorySnapshot[] snapshots)
            {
                values = new Queue<AssetStreamMemorySnapshot>(snapshots);
                if (values.Count == 0) throw new ArgumentException("snapshots");
                last = snapshots[snapshots.Length - 1];
            }

            internal int CaptureCount { get; private set; }

            public AssetStreamMemorySnapshot Capture()
            {
                CaptureCount++;
                if (values.Count != 0) last = values.Dequeue();
                return last;
            }
        }

        private sealed class HarnessUsageProbe : IAssetStreamExternalUsageProbe
        {
            private readonly long ui;
            private readonly long audio;
            internal HarnessUsageProbe(long uiBytes, long audioBytes)
            { ui = uiBytes; audio = audioBytes; }
            internal int CaptureCount { get; private set; }
            public AssetStreamExternalUsageSnapshot Capture()
            {
                CaptureCount++;
                return new AssetStreamExternalUsageSnapshot(ui, audio, string.Empty);
            }
        }

        private sealed class HarnessBackend :
            IAssetStreamGroupBackend<HarnessBaseline, HarnessCommitted>
        {
            private readonly HarnessMemoryProbe memory;
            internal HarnessBackend(HarnessMemoryProbe memoryValue) { memory = memoryValue; }
            internal int StageCount { get; private set; }
            internal int CommitCount { get; set; }
            internal int AbortCount { get; set; }
            internal int RestoreCount { get; private set; }
            internal int ReleaseCount { get; private set; }
            internal int MemoryCapturesAtCommit { get; set; }
            internal IList<string> LifecycleOrder { get; set; }
            public void Verify(AssetStreamGroupManifest group) { }
            public IAssetStreamGroupTransaction<HarnessCommitted> BeginTransaction(
                AssetStreamGroupManifest group,
                AssetStreamBaseline<HarnessBaseline> baseline,
                AssetStreamOwnershipToken ownership,
                AssetStreamCleanupCompletion cleanupCompletion)
            {
                StageCount++;
                Equal(1, memory.CaptureCount, "staging follows first probe");
                return new HarnessTransaction(this, memory);
            }
            public AssetStreamRestoreResult RestoreBaseline(
                AssetStreamGroupManifest group,
                AssetStreamBaseline<HarnessBaseline> baseline,
                AssetStreamOwnedGroup<HarnessCommitted> owned)
            {
                RestoreCount++;
                if (LifecycleOrder != null)
                {
                    LifecycleOrder.Add("restore");
                }
                return new AssetStreamRestoreResult(
                    AssetStreamRestoreDisposition.RestoredBaseline, true, "restored");
            }
            public AssetStreamReleaseResult Release(
                AssetStreamGroupManifest group,
                AssetStreamOwnedGroup<HarnessCommitted> owned)
            {
                ReleaseCount++;
                return new AssetStreamReleaseResult(true, false, "released");
            }

            private sealed class HarnessTransaction : IAssetStreamGroupTransaction<HarnessCommitted>
            {
                private readonly HarnessBackend owner;
                private readonly HarnessMemoryProbe memory;
                internal HarnessTransaction(HarnessBackend ownerValue, HarnessMemoryProbe memoryValue)
                { owner = ownerValue; memory = memoryValue; }
                public HarnessCommitted Commit()
                {
                    owner.CommitCount++;
                    owner.MemoryCapturesAtCommit = memory.CaptureCount;
                    if (memory.CaptureCount != 2)
                        throw new InvalidOperationException("publish occurred before second probe");
                    return new HarnessCommitted("runtime");
                }
                public void Abort() { owner.AbortCount++; }
                public void Dispose() { }
            }
        }
    }
}
#endif

#if UI_TEXTURE_HARNESS
using System;
using System.IO;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Dependency-free v2 contract, routing, budget, and source-surface tests.
    /// This source is empty in the production net481 assembly.
    /// </summary>
    internal static class UiTextureDependencyFreeHarness
    {
        private const string HashA =
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        private const string HashB =
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        private const string HashC =
            "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
        private const string HashD =
            "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        private static int _passed;

        public static int Main()
        {
            Run("strict v2 UI manifest", TestManifest);
            Run("compiled manifest file hash and size", TestCompiledManifestFile);
            Run("v2 provenance and padding rejection", TestManifestRejections);
            Run("generic Noesis virtual bridge", TestNoesisBridge);
            Run("legacy absolute PNG suffix ownership", TestLegacySuffixOwnership);
            Run("BC7 footprint and one-GiB budget", TestFootprintAndBudget);
            Run("bounded AssetBundle transient admission", TestTransientAdmission);
            Run("Noesis base-rewire provider guard", TestBaseReclaimContract);
            Run("no process-global unused-assets scan", TestNoGlobalUnusedAssetScan);
            Run("raw IEEE CRC32", TestCrc32);
            Run("transactional prefix installation", TestPatchTransaction);
            Run("direct BC7 runtime source surface", TestRuntimeSourceSurface);
            Console.WriteLine("UI BC7 texture harness passed=" + _passed);
            return 0;
        }

        private static void TestManifest()
        {
            string root = HarnessRoot();
            byte[] payload = Encoding.UTF8.GetBytes(ManifestText());
            UiTextureManifest manifest = UiTextureManifestParser.Parse(
                payload,
                root,
                2);
            Equal(2, manifest.Entries.Count, "entry count");
            Equal(2, manifest.Bundles.Count, "bundle count");
            Equal(96L, manifest.DeclaredGpuBytes, "BC7 byte sum");
            Equal(131180L, manifest.DeclaredResidentChargeBytes, "resident sum");
            Equal(3, manifest.Entries[0].LogicalWidth, "logical width");
            Equal(5, manifest.Entries[0].LogicalHeight, "logical height");
            Equal(4, manifest.Entries[0].StorageWidth, "padded width");
            Equal(8, manifest.Entries[0].StorageHeight, "padded height");
            Equal(32L, manifest.Entries[0].GpuBytes, "NPOT BC7 bytes");
            Equal(
                UiTextureManifestParser.BlockPaddingMode,
                manifest.Entries[0].BcBlockPadding,
                "padding mode");
            Equal(
                HashA,
                manifest.Provenance.SourceManifestSha256,
                "source provenance");

            var enabled = new UiTextureCompiledContract(
                true,
                UiTextureHash.Sha256(payload),
                payload.LongLength,
                2);
            True(enabled.Enabled, "enabled compiled contract");
            var disabled = new UiTextureCompiledContract(false, "", 0, 0);
            True(!disabled.Enabled, "empty disabled contract");
        }

        private static void TestManifestRejections()
        {
            string root = HarnessRoot();
            string source = ManifestText();
            Reject(
                source.Replace(
                    "unity_version\t2021.3.45f2",
                    "unity_version\t2021.3.46f1"),
                root,
                "Unity pin drift");
            Reject(
                source.Replace(
                    "source_schema\tstronghold-europe-de.ui-texture-sources.v1",
                    "source_schema\tother"),
                root,
                "source schema drift");
            Reject(
                source.Replace(
                    "bc_block_padding\tedge-extend-right-bottom-to-bc-block-v1",
                    "bc_block_padding\tnone"),
                root,
                "header padding drift");
            Reject(
                source.Replace("\t3\t5\t4\t8\t32\t", "\t3\t5\t8\t8\t32\t"),
                root,
                "storage padding mismatch");
            Reject(
                source.Replace("\t3\t5\t4\t8\t32\t", "\t3\t5\t4\t8\t64\t"),
                root,
                "GPU byte mismatch");
            Reject(
                source.Replace(
                    "declared_resident_charge_bytes\t131180",
                    "declared_resident_charge_bytes\t131179"),
                root,
                "resident sum mismatch");
            Reject(
                source.Replace("\t71303168\tui-bc7", "\t67108864\tui-bc7"),
                root,
                "transient formula mismatch");
            Reject(
                source.Replace(
                    "edge-extend-right-bottom-to-bc-block-v1\ntexture\tAssets/GUI/Sprites/two.private.png",
                    "none\ntexture\tAssets/GUI/Sprites/two.private.png"),
                root,
                "row padding drift");
            Reject(source.Replace("\n", "\r\n"), root, "CRLF ambiguity");
            Reject(source + "\n", root, "extra terminal blank line");
            Reject(
                source.Replace("entry_count\t2", "entry_count\t02"),
                root,
                "noncanonical integer");
            Reject(
                source.Replace(
                    "Assets/GUI/Sprites/two.private.png",
                    "Assets/GUI/Images/../two.private.png"),
                root,
                "relative traversal");
            Throws<UiTextureContractException>(
                delegate
                {
                    UiTextureManifestParser.Parse(
                        PrefixBom(Encoding.UTF8.GetBytes(source)),
                        root,
                        2);
                },
                "BOM rejection");
            Throws<ArgumentException>(
                delegate { new UiTextureCompiledContract(false, HashA, 1, 1); },
                "disabled digest placeholder rejection");
        }

        private static void TestCompiledManifestFile()
        {
            string root = Path.Combine(
                Path.GetTempPath(),
                "StrongholdEuropeDE-UiTexture-Manifest-"
                    + Guid.NewGuid().ToString("N"));
            string runtime = Path.Combine(root, "Runtime");
            Directory.CreateDirectory(runtime);
            byte[] payload = Encoding.UTF8.GetBytes(ManifestText());
            string path = Path.Combine(runtime, "ui-textures-v2.tsv");
            File.WriteAllBytes(path, payload);
            try
            {
                var exact = new UiTextureCompiledContract(
                    true,
                    UiTextureHash.Sha256(payload),
                    payload.LongLength,
                    2);
                Equal(
                    2,
                    UiTextureManifest.Load(root, exact).Entries.Count,
                    "compiled manifest loaded exactly");

                var wrongHash = new UiTextureCompiledContract(
                    true,
                    HashA,
                    payload.LongLength,
                    2);
                Throws<UiTextureContractException>(
                    delegate { UiTextureManifest.Load(root, wrongHash); },
                    "compiled manifest hash mismatch");

                var wrongSize = new UiTextureCompiledContract(
                    true,
                    UiTextureHash.Sha256(payload),
                    checked(payload.LongLength + 1L),
                    2);
                Throws<UiTextureContractException>(
                    delegate { UiTextureManifest.Load(root, wrongSize); },
                    "compiled manifest size mismatch");
            }
            finally
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        private static void TestNoesisBridge()
        {
            UiTextureManifest manifest = ParseManifest();
            UiTextureModIconBridge bridge =
                UiTextureModIconBridge.CreateIfPresent(manifest);
            string resolved;
            True(
                bridge.TryResolve("Assets/GUI/Images/one.png", out resolved),
                "exact Noesis path resolved");
            Equal(
                manifest.Entries[0].VirtualAbsolutePath,
                resolved,
                "virtual path returned");
            True(
                bridge.TryResolve("Assets/GUI/Images/one", out resolved),
                "extensionless SHCDE-SE request resolved");
            True(
                bridge.TryResolve("Assets/GUI/Sprites/two.private", out resolved),
                "dotted extensionless SHCDE-SE request resolved");
            True(
                bridge.TryResolve("Assets\\GUI\\Images\\one.png", out resolved),
                "backslash request normalized");
            True(
                !bridge.TryResolve("assets/GUI/Images/one.png", out resolved),
                "case-variant Noesis URI remains original");
            True(
                !bridge.TryResolve("Assets/GUI/Images/unowned.png", out resolved),
                "unowned Noesis path remains original");
            True(
                !bridge.TryResolve("Assets/GUI/Images/one.jpg", out resolved),
                "wrong extension remains original");
        }

        private static void TestLegacySuffixOwnership()
        {
            UiTextureManifest manifest = ParseManifest();
            UiTextureManifestEntry entry;
            True(
                manifest.TryFindOwnedLoadPath(
                    manifest.Entries[0].VirtualAbsolutePath,
                    out entry),
                "exact virtual path owned");
            Equal(
                manifest.Entries[0].NoesisPath,
                entry.NoesisPath,
                "virtual lookup entry");

            string external = Path.Combine(
                Path.GetTempPath(),
                "OtherCampaignPlugin",
                "Override",
                "Assets",
                "GUI",
                "Images",
                "one.png");
            True(
                manifest.TryFindOwnedLoadPath(external, out entry),
                "external legacy PNG suffix owned fail-closed");
            True(
                manifest.TryFindOwnedLoadPath(
                    external.ToUpperInvariant(),
                    out entry),
                "legacy Windows case variant owned fail-closed");
            True(
                !manifest.TryFindOwnedLoadPath(
                    external.Replace("Override", "OverrideX"),
                    out entry),
                "near-miss directory unowned");
            True(
                !manifest.TryFindOwnedLoadPath(
                    external.Replace("one.png", "unowned.png"),
                    out entry),
                "unlisted legacy PNG unowned");
        }

        private static void TestFootprintAndBudget()
        {
            long gpu;
            long resident;
            True(
                UiTextureFootprint.TryCalculateBc7Bytes(4, 8, out gpu),
                "4x8 BC7 footprint");
            Equal(32L, gpu, "4x8 BC7 bytes");
            True(
                UiTextureFootprint.TryCalculateResidentChargeBytes(
                    gpu,
                    out resident),
                "resident formula");
            Equal(65572L, resident, "resident formula exact");
            True(
                !UiTextureFootprint.TryCalculateBc7Bytes(3, 8, out gpu),
                "unpadded storage rejected");
            True(
                UiTextureFootprint.TryCalculateBc7Bytes(8192, 8192, out gpu),
                "maximum texture accepted");
            Equal(64L * 1024L * 1024L, gpu, "maximum BC7 bytes");

            var ledger = new UiTextureBudgetLedger(100);
            UiTextureBudgetReservation first;
            UiTextureBudgetReservation denied;
            string failure;
            True(ledger.TryReserve(60, out first, out failure), "first reserve");
            True(
                !ledger.TryReserve(41, out denied, out failure),
                "over-budget reserve denied");
            first.Commit();
            UiTextureBudgetSnapshot snapshot = ledger.Snapshot();
            Equal(60L, snapshot.CommittedBytes, "committed resident bytes");
            Equal(1, snapshot.CommittedTextureCount, "committed texture count");
            True(
                ledger.TryReserve(40, out denied, out failure),
                "exact remaining budget admitted");
            denied.Cancel();
            Equal(
                1024L * 1024L * 1024L,
                UiTextureBudgetLedger.MaximumProcessResidentBytes,
                "one-GiB hard budget");
        }

        private static void TestTransientAdmission()
        {
            Equal(
                4L * 1024L * 1024L * 1024L,
                UiTextureTransientAdmission.GlobalCommitReserveBytes,
                "four-GiB commit reserve");
            Equal(
                256L * 1024L * 1024L,
                UiTextureTransientAdmission.MinimumFreePhysicalBytes,
                "256-MiB absolute physical floor");
            // Must track process_private_ceiling_bytes of
            // windows_24gb_igpu_bc7_12gib_process_private_v5. V3 shipped 16 GiB
            // in both lanes; V4 corrected only the GM side, so this lane kept
            // admitting long after the GM lane had started denying.
            Equal(
                12L * 1024L * 1024L * 1024L,
                UiTextureTransientAdmission.ProcessPrivateCeilingBytes,
                "eight-GiB process-private ceiling matches the V4 GM policy");
            long peak;
            True(
                UiTextureTransientAdmission.TryCalculatePeakBytes(
                    32,
                    101,
                    out peak),
                "small bundle peak calculated");
            Equal(68L * 1024L * 1024L, peak, "4-MiB aligned peak");
            string failure;
            True(
                UiTextureTransientAdmission.TryAdmit(
                    peak,
                    4L * 1024L * 1024L * 1024L,
                    16L * 1024L * 1024L * 1024L,
                    8L * 1024L * 1024L * 1024L,
                    out failure),
                "healthy memory snapshot admitted");
            True(
                !UiTextureTransientAdmission.TryAdmit(
                    peak,
                    null,
                    16L * 1024L * 1024L * 1024L,
                    8L * 1024L * 1024L * 1024L,
                    out failure),
                "missing metric rejected");

            long near250MibPeak;
            True(
                UiTextureTransientAdmission.TryCalculatePeakBytes(
                    64L * 1024L * 1024L,
                    56L * 1024L * 1024L,
                    out near250MibPeak),
                "near-250-MiB peak calculated");
            Equal(248L * 1024L * 1024L, near250MibPeak,
                "near-250-MiB exact peak");
            long physical095Gib = 19L * 1024L * 1024L * 1024L / 20L;
            // Comfortably inside the ceiling, whatever the ceiling is.
            long healthyPrivateBytes =
                UiTextureTransientAdmission.ProcessPrivateCeilingBytes / 2L;
            True(
                UiTextureTransientAdmission.TryAdmit(
                    near250MibPeak,
                    healthyPrivateBytes,
                    UiTextureTransientAdmission.GlobalCommitReserveBytes
                        + near250MibPeak,
                    physical095Gib,
                    out failure),
                "0.95 GiB physical with valid commit admits near-250-MiB peak");
            True(
                UiTextureTransientAdmission.TryAdmit(
                    near250MibPeak,
                    healthyPrivateBytes,
                    16L * 1024L * 1024L * 1024L,
                    UiTextureTransientAdmission.MinimumFreePhysicalBytes,
                    out failure),
                "absolute physical floor does not add transient peak");
            True(
                !UiTextureTransientAdmission.TryAdmit(
                    near250MibPeak,
                    healthyPrivateBytes,
                    16L * 1024L * 1024L * 1024L,
                    UiTextureTransientAdmission.MinimumFreePhysicalBytes - 1,
                    out failure),
                "below absolute physical floor rejected");
            True(
                !UiTextureTransientAdmission.TryAdmit(
                    near250MibPeak,
                    healthyPrivateBytes,
                    UiTextureTransientAdmission.GlobalCommitReserveBytes
                        + near250MibPeak - 1,
                    physical095Gib,
                    out failure),
                "insufficient available commit rejected");
            True(
                !UiTextureTransientAdmission.TryAdmit(
                    near250MibPeak,
                    UiTextureTransientAdmission.ProcessPrivateCeilingBytes
                        - near250MibPeak + 1,
                    16L * 1024L * 1024L * 1024L,
                    physical095Gib,
                    out failure),
                "insufficient process-private headroom rejected");
        }

        private static void TestBaseReclaimContract()
        {
            string failure;
            True(
                UiTextureBaseReclaimContract.TryValidateProviderState(
                    1,
                    true,
                    out failure),
                "single owned provider reference is valid");
            True(
                UiTextureBaseReclaimContract.TryValidateProviderState(
                    4,
                    true,
                    out failure),
                "duplicate XAML registrations remain valid and preserved");
            True(
                !UiTextureBaseReclaimContract.TryValidateProviderState(
                    0,
                    true,
                    out failure),
                "missing provider reference is rejected");
            True(
                !UiTextureBaseReclaimContract.TryValidateProviderState(
                    2,
                    false,
                    out failure),
                "foreign current provider texture is rejected");
            True(
                !UiTextureBaseReclaimContract.TryValidateProviderState(
                    -1,
                    true,
                    out failure),
                "negative provider reference count is rejected");
        }

        private static void TestNoGlobalUnusedAssetScan()
        {
            string root = FindRepositoryRoot();
            string reclaim = File.ReadAllText(Path.Combine(
                root,
                "runtime",
                "StrongholdEuropeDE.Runtime",
                "UiTextureBaseTextureReclaimer.cs"));
            NotContains(
                reclaim,
                "Resources.UnloadUnusedAssets()",
                "UI base reclaim releases only its exact displaced textures");
            NotContains(
                reclaim,
                "UnusedAssetScanArbiter",
                "UI base reclaim owns no process-global scan arbitration");
        }

        private static void TestCrc32()
        {
            Equal(
                "cbf43926",
                UiTextureCrc32.ComputeHex(Encoding.ASCII.GetBytes("123456789")),
                "zlib/IEEE CRC32 vector");
        }

        private static void TestPatchTransaction()
        {
            int installed = 0;
            int rolledBack = 0;
            UiTexturePatchTransaction.Apply(
                delegate { installed = 1; },
                delegate { installed = 2; },
                delegate { rolledBack++; });
            Equal(2, installed, "both prefixes installed");
            Equal(0, rolledBack, "no rollback on success");

            installed = 0;
            Throws<InvalidOperationException>(
                delegate
                {
                    UiTexturePatchTransaction.Apply(
                        delegate { installed = 1; },
                        delegate { throw new InvalidOperationException("bridge"); },
                        delegate { rolledBack++; });
                },
                "bridge failure propagated");
            Equal(1, installed, "loader installed before bridge failure");
            Equal(1, rolledBack, "owner rolled back transactionally");
        }

        private static void TestRuntimeSourceSurface()
        {
            string root = FindRepositoryRoot();
            string runtime = File.ReadAllText(Path.Combine(
                root,
                "runtime",
                "StrongholdEuropeDE.Runtime",
                "UiTextureRuntimeLane.cs"));
            string patch = File.ReadAllText(Path.Combine(
                root,
                "runtime",
                "StrongholdEuropeDE.Runtime",
                "UiTextureLoadTexturePatch.cs"));
            string reclaim = File.ReadAllText(Path.Combine(
                root,
                "runtime",
                "StrongholdEuropeDE.Runtime",
                "UiTextureBaseTextureReclaimer.cs"));
            string active = runtime + "\n" + patch + "\n" + reclaim;
            Contains(runtime, "AssetBundle.LoadFromStream(", "direct bundle load");
            Contains(runtime, "bundle.LoadAsset<Texture2D>(", "direct texture load");
            Contains(runtime, "bundle.Unload(false);", "texture retained on unload");
            Contains(runtime, "texture.format != TextureFormat.BC7", "BC7 validation");
            Contains(runtime, "texture.width != entry.StorageWidth", "storage width validation");
            Contains(runtime, "texture.height != entry.StorageHeight", "storage height validation");
            Contains(runtime, "texture.isReadable", "unreadable validation");
            Contains(runtime, "texture.isDataSRGB", "sRGB validation");
            Contains(runtime, "texture.filterMode", "filter validation");
            Contains(runtime, "texture.wrapMode", "clamp validation");
            Contains(runtime, "texture.wrapModeU", "clamp-U validation");
            Contains(runtime, "texture.wrapModeV", "clamp-V validation");
            Contains(runtime, "texture.wrapModeW", "clamp-W validation");
            Contains(runtime, "UiTextureCrc32.Update(", "streaming CRC validation");
            Contains(active, "RejectedOwnedTexture", "owned rejection disposition");
            Contains(patch, "RejectOwnedFailClosed", "outer fail-closed guard");
            Contains(patch, "TryResolveTexturePath", "SHCDE-SE resolver bridge");
            Contains(
                reclaim,
                "Resources.FindObjectsOfTypeAll(_xamlType)",
                "reflection-only built-in Noesis dependency inventory");
            // The former assertion pinned "ResolveBridge().UpdateTextures();"
            // and called it a native pointer flush. It was not one: Noesis'
            // UpdateTextures stores nothing when _texturesRequested is empty
            // and ends in an unconditional Clear(), so calling it out of band
            // could consume a request Noesis raised in the same frame. The
            // rewire now requires the queue to be already drained instead.
            Contains(
                reclaim,
                "GetPendingRequestCount()",
                "rewire requires an already drained Noesis request queue");
            NotContains(
                reclaim,
                "ResolveBridge().UpdateTextures();",
                "no out-of-band UpdateTextures call");
            Contains(
                reclaim,
                "bridge.SetDependencyTexture(",
                "built-in dependency rewired to BC7 override");
            Contains(
                reclaim,
                "group.OwnedOverride",
                "owned BC7 texture is the rewire target");
            Contains(
                reclaim,
                "RetainXamls(ownerObjects);",
                "rewired XAML lifetime retained across unused-assets scan");
            Contains(
                reclaim,
                "ExpectedReadableRgba32 = 98",
                "pinned readable RGBA32 base provenance");
            Contains(
                reclaim,
                "ExpectedReadableRgb24 = 7",
                "pinned readable RGB24 base provenance");
            Contains(
                reclaim,
                "ExpectedReadableBc7 = 8",
                "pinned readable BC7 base provenance");
            Contains(
                reclaim,
                "ExpectedDependencies = 116",
                "duplicate Noesis dependency provenance");
            NotContains(
                reclaim,
                "Resources.UnloadUnusedAssets();",
                "no process-global unused-assets scan");
            // The reclaim used to be gated on all 114 manifest paths having
            // loaded. That could never happen - the mod logo has no Override
            // PNG, so SHCDE-SE never requests it - which left the reclaim
            // permanently unarmed. It now arms on the first owned load and the
            // host waits for the lane to settle.
            NotContains(
                patch,
                "_loaded == _lane.Manifest.Entries.Count",
                "reclaim is no longer gated on a fixed manifest count");
            Contains(
                patch,
                "SnapshotProgress",
                "reclaim host observes lane progress");
            Contains(
                reclaim,
                "SettleMilliseconds",
                "reclaim waits for the UI lane to settle");
            Contains(
                reclaim,
                "status=never_armed",
                "a reclaim that never arms is visible in the log");
            Contains(
                reclaim,
                "ROLLBACK INCOMPLETE",
                "a partial rollback is a loud terminal state");
            Contains(
                reclaim,
                "RepairProviderTexture(",
                "watchdog repairs the provider value in place");
            NotContains(
                reclaim,
                ".Register(",
                "watchdog never calls Register, which would increment refs");
            Contains(
                runtime,
                "HideFlags.DontUnloadUnusedAsset",
                "owned BC7 textures are exempt from every unused-assets scan");
            Contains(
                reclaim,
                "Resources.UnloadAsset(candidate)",
                "base textures are released individually, never by a global scan");
            Contains(
                reclaim,
                "AssetStreamRuntimeLane.AnyBaselineCaptured",
                "the release waits for the AssetStream baseline capture");
            NotContains(
                File.ReadAllText(Path.Combine(
                    root,
                    "runtime",
                    "StrongholdEuropeDE.Runtime",
                    "AssetStreamUnityBackend.cs")),
                "UnusedAssetScanArbiter",
                "the UI reclaim never reaches into the AssetStream backend at all");
            NotContains(
                reclaim,
                ".Unregister(",
                "Noesis provider registration lifetime remains untouched");

            NotContains(active, "LoadImage", "no runtime image decode");
            NotContains(active, "GetPixels", "no runtime pixel readback");
            NotContains(active, "SetPixels", "no runtime pixel upload");
            NotContains(runtime, ".Apply(", "no runtime texture apply");
            NotContains(active, "new Texture2D", "no runtime RGBA allocation");
        }

        private static UiTextureManifest ParseManifest()
        {
            return UiTextureManifestParser.Parse(
                Encoding.UTF8.GetBytes(ManifestText()),
                HarnessRoot(),
                2);
        }

        private static void Reject(string text, string root, string message)
        {
            Throws<UiTextureContractException>(
                delegate
                {
                    UiTextureManifestParser.Parse(
                        Encoding.UTF8.GetBytes(text),
                        root,
                        2);
                },
                message);
        }

        private static string ManifestText()
        {
            const string firstPath = "Assets/GUI/Images/one.png";
            const string secondPath = "Assets/GUI/Sprites/two.private.png";
            string firstHash = UiTextureHash.Sha256Utf8(firstPath).Substring(0, 16);
            string secondHash = UiTextureHash.Sha256Utf8(secondPath).Substring(0, 16);
            return
                "stronghold-europe-ui-textures\t2\n"
                + "source_schema\tstronghold-europe-de.ui-texture-sources.v1\n"
                + "source_manifest_sha256\t" + HashA + "\n"
                + "source_entry_set_sha256\t" + HashB + "\n"
                + "quality_policy_schema\tstronghold-europe-de.ui-bc7-quality-policy.v1\n"
                + "quality_policy_id\tbc7_ui_visual_equivalence_v1\n"
                + "quality_policy_sha256\t" + HashC + "\n"
                + "quality_verifier_id\tunitypy-1.25.3-ui-bc7-premultiplied-metrics-v1\n"
                + "encoder_id\tunity-2021.3.45f2-bc7-hq100-force-max-ui-v1\n"
                + "editor_source_sha256\t" + HashD + "\n"
                + "unity_version\t2021.3.45f2\n"
                + "unity_revision\t88f88f591b2e\n"
                + "alpha_mode\tpremultiply-u8-round-nearest-v1\n"
                + "bc_block_padding\tedge-extend-right-bottom-to-bc-block-v1\n"
                + "entry_count\t2\n"
                + "bundle_count\t2\n"
                + "declared_gpu_bytes\t96\n"
                + "declared_resident_charge_bytes\t131180\n"
                + "bundle\tid\tplugin_relative_path\tsha256\tsize_bytes\tcrc32\tunity_hash128\n"
                + "bundle\ta\tRuntime/UiAssetBundles/win64/sede.ui."
                + firstHash + ".bc7.v1\t" + HashA
                + "\t101\t12345678\t11111111111111111111111111111111\n"
                + "bundle\tb\tRuntime/UiAssetBundles/win64/sede.ui."
                + secondHash + ".bc7.v1\t" + HashB
                + "\t202\t87654321\t22222222222222222222222222222222\n"
                + "texture\tnoesis_path\tvirtual_relative_path\tbundle_id\taddress"
                + "\tsource_png_sha256\tpremultiplied_rgba_sha256"
                + "\tlogical_width\tlogical_height\tstorage_width\tstorage_height"
                + "\tgpu_bytes\tresident_charge_bytes\ttransient_peak_bytes"
                + "\ttexture_contract_id\tbc_block_padding\n"
                + "texture\t" + firstPath
                + "\tRuntime/UiTextures/virtual/" + firstHash + ".png\ta"
                + "\tsede/ui/" + firstHash + "/texture\t" + HashA + "\t" + HashB
                + "\t3\t5\t4\t8\t32\t65572\t71303168"
                + "\tui-bc7-point-premultiplied-v1"
                + "\tedge-extend-right-bottom-to-bc-block-v1\n"
                + "texture\t" + secondPath
                + "\tRuntime/UiTextures/virtual/" + secondHash + ".png\tb"
                + "\tsede/ui/" + secondHash + "/texture\t" + HashB + "\t" + HashC
                + "\t8\t8\t8\t8\t64\t65608\t71303168"
                + "\tui-bc7-bilinear-premultiplied-v1"
                + "\tedge-extend-right-bottom-to-bc-block-v1\n";
        }

        private static byte[] PrefixBom(byte[] payload)
        {
            var result = new byte[payload.Length + 3];
            result[0] = 0xef;
            result[1] = 0xbb;
            result[2] = 0xbf;
            Array.Copy(payload, 0, result, 3, payload.Length);
            return result;
        }

        private static string HarnessRoot()
        {
            return Path.Combine(
                Path.GetTempPath(),
                "StrongholdEuropeDE-UiTexture-BC7-Harness");
        }

        private static string FindRepositoryRoot()
        {
            DirectoryInfo current = new DirectoryInfo(Environment.CurrentDirectory);
            while (current != null)
            {
                if (File.Exists(Path.Combine(
                        current.FullName,
                        "runtime",
                        "StrongholdEuropeDE.Runtime",
                        "UiTextureRuntimeLane.cs")))
                {
                    return current.FullName;
                }
                current = current.Parent;
            }
            throw new DirectoryNotFoundException("repository root not found");
        }

        private static void Run(string name, Action action)
        {
            try
            {
                action();
                _passed++;
                Console.WriteLine("PASS " + name);
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine("FAIL " + name + ": " + exception);
                throw;
            }
        }

        private static void True(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
        }

        private static void Contains(string value, string token, string message)
        {
            if (value.IndexOf(token, StringComparison.Ordinal) < 0)
            {
                throw new InvalidOperationException(message + " missing: " + token);
            }
        }

        private static void NotContains(string value, string token, string message)
        {
            if (value.IndexOf(token, StringComparison.Ordinal) >= 0)
            {
                throw new InvalidOperationException(message + " found: " + token);
            }
        }

        private static void Equal<T>(T expected, T actual, string message)
        {
            if (!object.Equals(expected, actual))
            {
                throw new InvalidOperationException(
                    message + " expected=" + expected + " actual=" + actual);
            }
        }

        private static void Throws<T>(Action action, string message)
            where T : Exception
        {
            try
            {
                action();
            }
            catch (T)
            {
                return;
            }
            throw new InvalidOperationException(message);
        }
    }
}
#endif
